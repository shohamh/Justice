# Batch 4 — Swaps: Draft & Received Duties Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a soldier ask for a swap on a duty they hold only because they received it via a prior swap, and on duties that are still in `algorithm_draft` status; and let both the swap-ask and cover/trade UIs actually list those duties, without letting draft duties leak into scoring/effort.

**Architecture:** Two small, independent fixes plus one shared plumbing change:
1. `swaps.create_request`'s ownership/status gate is rewritten to resolve the *effective* owner of a duty for a given day (accounting for `DutyDayOverride` rows written by earlier swaps) instead of comparing against `DutyAssignment.soldier_id` directly, and to accept `algorithm_draft` status alongside `published`.
2. A new, explicitly-named listing function (`swap_surface_duty_spans`) is added alongside the existing `effective_duty_spans` in `scoring.py`, sharing the per-assignment span-expansion logic via an extracted helper. The existing function is untouched and stays published-only (scoring/effort must never see drafts); the new one adds `algorithm_draft` and is used **only** by the `GET /assignments/effective?for_swap=true` opt-in path that feeds the swap/cover UI.
3. `SwapsPage.tsx` and `OfferSwapModal.tsx` pass `for_swap: true` when fetching "my duties" so drafts and received-via-swap duties show up with the ask-swap button and in trade-offer pickers; `CoverOfferModal.tsx` gets the same clear empty-state copy `OfferSwapModal` already has.

**Tech Stack:** FastAPI + SQLAlchemy (backend), React + TanStack Query + vitest (frontend), pytest (backend tests).

## Global Constraints

- **Scoring/effort isolation (DC4/DC5):** `algorithm_draft` assignments must never enter `effective_duty_spans`, `shift_count_by_soldier`, or any other scoring/effort/fairness input. Only the new `swap_surface_duty_spans` function and its `for_swap=true` route path may include them.
- **RBAC:** no authorization changes in this batch — `create_request`'s existing `authorize`-free ownership check is being made *correct* (recognize the true current owner), not loosened to allow arbitrary soldiers.
- **Tests:** backend tests use `pytest -q` (markers: this batch's new tests live under the `duty` marker via file location, auto-assigned — no manual marker needed). Frontend: `npm run typecheck`, `npm run lint` (zero warnings), `npm test`.
- **i18n:** reuse the existing `swaps.no_duties` key (`"אין תורנויות להצגה"`) for the new empty-state copy — do not add a new translation key for this.

---

### Task 1: `create_request` recognizes the effective owner and accepts draft duties

**Files:**
- Modify: `backend/app/services/swaps.py:12-14` (imports), `backend/app/services/swaps.py:85-91` (ownership/status gate)
- Test: `backend/tests/unit/test_swaps_service.py`

**Interfaces:**
- Produces: `_effective_soldier_on_date(session, *, assignment: DutyAssignment, day: date) -> uuid.UUID | None` — a private helper in `swaps.py`. Not consumed by later tasks (self-contained to `create_request`).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/unit/test_swaps_service.py` (append to the file, after the existing helpers/tests):

```python
def _draft_assignment(session, *, soldier_id):
    from app.db.models import DutyType, DutyLocation
    dt = DutyType(name=f"dt_draft_{soldier_id}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_draft_{soldier_id}")
    session.add_all([dt, loc])
    session.flush()
    a = DutyAssignment(
        soldier_id=soldier_id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() + timedelta(days=10), end_date=date.today() + timedelta(days=11),
        status="algorithm_draft",
    )
    session.add(a)
    session.flush()
    return a


def test_create_request_allowed_on_draft_assignment(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-draft-1")
    requester = create_soldier(admin_session, personal_number="7710010", hierarchy_node_id=node.id)
    assignment = _draft_assignment(admin_session, soldier_id=requester.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=None, reason=None, open_to_marketplace=True,
    )

    assert req.status == "open"


def test_create_request_allowed_for_soldier_who_received_duty_via_swap(admin_session):
    from app.services import assignments as assignments_svc

    node = create_node(admin_session, level="unit", name="swap-svc-received-1")
    original_owner = create_soldier(admin_session, personal_number="7710011", hierarchy_node_id=node.id)
    receiver = create_soldier(admin_session, personal_number="7710012", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=original_owner.id, node_id=node.id)

    assignments_svc.set_day_override(
        admin_session, assignment=assignment, date=assignment.start_date,
        effective_soldier_id=receiver.id, reason="replacement",
    )
    admin_session.flush()

    req = svc.create_request(
        admin_session, requesting_soldier_id=receiver.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=None, reason=None, open_to_marketplace=True,
    )
    assert req.status == "open"

    with pytest.raises(SwapError, match="not_your_duty"):
        svc.create_request(
            admin_session, requesting_soldier_id=original_owner.id, duty_assignment_id=assignment.id,
            target_soldier_id=None, target_soldier_ids=None, reason=None, open_to_marketplace=True,
        )


def test_create_request_still_rejects_unrelated_soldier(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-unrelated-1")
    owner = create_soldier(admin_session, personal_number="7710013", hierarchy_node_id=node.id)
    stranger = create_soldier(admin_session, personal_number="7710014", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=owner.id, node_id=node.id)

    with pytest.raises(SwapError, match="not_your_duty"):
        svc.create_request(
            admin_session, requesting_soldier_id=stranger.id, duty_assignment_id=assignment.id,
            target_soldier_id=None, target_soldier_ids=None, reason=None, open_to_marketplace=True,
        )


def test_create_request_still_rejects_non_draft_non_published_assignment(admin_session):
    from app.db.models import DutyType, DutyLocation

    node = create_node(admin_session, level="unit", name="swap-svc-cancelled-1")
    owner = create_soldier(admin_session, personal_number="7710015", hierarchy_node_id=node.id)
    dt = DutyType(name="dt_cancelled_1", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="loc_cancelled_1")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    a = DutyAssignment(
        soldier_id=owner.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() + timedelta(days=10), end_date=date.today() + timedelta(days=11),
        status="cancelled",
    )
    admin_session.add(a)
    admin_session.flush()

    with pytest.raises(SwapError, match="not_published"):
        svc.create_request(
            admin_session, requesting_soldier_id=owner.id, duty_assignment_id=a.id,
            target_soldier_id=None, target_soldier_ids=None, reason=None, open_to_marketplace=True,
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_swaps_service.py -k "draft_assignment or received_duty_via_swap or unrelated_soldier or non_draft_non_published" -v`
Expected: `test_create_request_allowed_on_draft_assignment` and `test_create_request_allowed_for_soldier_who_received_duty_via_swap` FAIL (current code raises `not_published`/`not_your_duty`); the other two PASS already (they assert today's correct behavior).

- [ ] **Step 3: Add the imports**

In `backend/app/services/swaps.py`, change the `app.db.models` import block (currently lines 12-14):

```python
from app.db.models import (
    DutyAssignment, HierarchyNode, NotificationType, Soldier, SwapCandidate, SwapManagerApproval, SwapRequest,
)
```

to:

```python
from app.db.models import (
    DutyAssignment, DutyDayOverride, DutyDismissal, HierarchyNode, NotificationType, Soldier, SwapCandidate,
    SwapManagerApproval, SwapRequest,
)
```

- [ ] **Step 4: Add the effective-owner helper**

In `backend/app/services/swaps.py`, insert this function right after `_max_specific_targets` (currently ending at line 58) and before `def create_request(`:

```python
def _effective_soldier_on_date(
    session: Session, *, assignment: DutyAssignment, day: date,
) -> uuid.UUID | None:
    """Who actually owns `assignment` on `day`. A prior swap only ever writes
    a DutyDayOverride — it never mutates DutyAssignment.soldier_id — so a
    soldier who received this duty via swap is only discoverable through the
    override, not through the assignment's nominal owner. None means the day
    is dismissed and unowned."""
    ov = session.execute(
        select(DutyDayOverride).where(
            DutyDayOverride.duty_assignment_id == assignment.id,
            DutyDayOverride.date == day,
        )
    ).scalar_one_or_none()
    if ov is not None:
        return ov.effective_soldier_id
    dismissed = session.execute(
        select(DutyDismissal).where(
            DutyDismissal.duty_assignment_id == assignment.id,
            DutyDismissal.dismissed_from <= day,
            DutyDismissal.dismissed_to >= day,
        )
    ).first()
    if dismissed is not None:
        return None
    return assignment.soldier_id
```

- [ ] **Step 5: Rewrite the ownership/status gate**

In `backend/app/services/swaps.py`, change (currently lines 85-91):

```python
    assignment = session.get(DutyAssignment, duty_assignment_id)
    if assignment is None:
        raise SwapError("assignment_not_found")
    if assignment.soldier_id != requesting_soldier_id:
        raise SwapError("not_your_duty")
    if assignment.status != "published":
        raise SwapError("not_published")
```

to:

```python
    assignment = session.get(DutyAssignment, duty_assignment_id)
    if assignment is None:
        raise SwapError("assignment_not_found")
    if _effective_soldier_on_date(session, assignment=assignment, day=assignment.start_date) != requesting_soldier_id:
        raise SwapError("not_your_duty")
    if assignment.status not in ("published", "algorithm_draft"):
        raise SwapError("not_published")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/unit/test_swaps_service.py -k "draft_assignment or received_duty_via_swap or unrelated_soldier or non_draft_non_published" -v`
Expected: all 4 PASS.

- [ ] **Step 7: Run the full swaps test suites to check for regressions**

Run: `pytest tests/unit/test_swaps.py tests/unit/test_swaps_service.py tests/integration/test_swaps_api.py tests/integration/test_swaps_eligibility.py -q`
Expected: all PASS, 0 failures.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/swaps.py backend/tests/unit/test_swaps_service.py
git commit -m "fix: allow swap-ask on drafts and duties received via a prior swap"
```

---

### Task 2: `scoring.py` gains a swap-surface listing that includes drafts, without touching scoring

**Files:**
- Modify: `backend/app/services/scoring.py:108-201`
- Test: Create `backend/app/services/tests/test_scoring_swap_surfaces.py`

**Interfaces:**
- Consumes: nothing new (pure refactor + addition within `scoring.py`).
- Produces:
  - `effective_duty_spans(session, *, soldier_ids=None, date_from=None, date_to=None) -> list[dict[str, Any]]` — **unchanged signature and behavior**, published-only.
  - `swap_surface_duty_spans(session, *, soldier_ids=None, date_from=None, date_to=None) -> list[dict[str, Any]]` — same return shape as `effective_duty_spans`, but includes `algorithm_draft` assignments too. Consumed by Task 3.

- [ ] **Step 1: Write the failing tests**

Create `backend/app/services/tests/test_scoring_swap_surfaces.py`:

```python
import uuid
from datetime import date, timedelta
from decimal import Decimal

from app.db.models import DutyAssignment, DutyLocation, DutyType
from app.services.scoring import effective_duty_spans, shift_count_by_soldier, swap_surface_duty_spans
from tests.helpers import create_node, create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def _assignment(session, *, soldier_id, status):
    dt = DutyType(name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    session.add_all([dt, loc])
    session.flush()
    a = DutyAssignment(
        soldier_id=soldier_id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=6),
        status=status,
    )
    session.add(a)
    session.flush()
    return a


def test_draft_assignment_excluded_from_effective_duty_spans(admin_session):
    node = create_node(admin_session, level="unit", name=f"scoring-swap-{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"77200{_uid()[:3]}", hierarchy_node_id=node.id)
    _assignment(admin_session, soldier_id=soldier.id, status="algorithm_draft")

    spans = effective_duty_spans(admin_session, soldier_ids={soldier.id})

    assert spans == []


def test_draft_assignment_included_in_swap_surface_duty_spans(admin_session):
    node = create_node(admin_session, level="unit", name=f"scoring-swap-{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"77201{_uid()[:3]}", hierarchy_node_id=node.id)
    a = _assignment(admin_session, soldier_id=soldier.id, status="algorithm_draft")

    spans = swap_surface_duty_spans(admin_session, soldier_ids={soldier.id})

    assert len(spans) == 1
    assert spans[0]["assignment_id"] == a.id
    assert spans[0]["soldier_id"] == soldier.id


def test_published_assignment_present_in_both(admin_session):
    node = create_node(admin_session, level="unit", name=f"scoring-swap-{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"77202{_uid()[:3]}", hierarchy_node_id=node.id)
    a = _assignment(admin_session, soldier_id=soldier.id, status="published")

    eff_spans = effective_duty_spans(admin_session, soldier_ids={soldier.id})
    swap_spans = swap_surface_duty_spans(admin_session, soldier_ids={soldier.id})

    assert len(eff_spans) == 1 and eff_spans[0]["assignment_id"] == a.id
    assert len(swap_spans) == 1 and swap_spans[0]["assignment_id"] == a.id


def test_shift_count_by_soldier_ignores_drafts(admin_session):
    node = create_node(admin_session, level="unit", name=f"scoring-swap-{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"77203{_uid()[:3]}", hierarchy_node_id=node.id)
    _assignment(admin_session, soldier_id=soldier.id, status="algorithm_draft")

    counts = shift_count_by_soldier(admin_session)

    assert counts.get(soldier.id, 0) == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest app/services/tests/test_scoring_swap_surfaces.py -v`
Expected: `test_draft_assignment_included_in_swap_surface_duty_spans` and `test_published_assignment_present_in_both` FAIL with `ImportError: cannot import name 'swap_surface_duty_spans'`. The other two pass already against current `effective_duty_spans`.

- [ ] **Step 3: Refactor `scoring.py`**

In `backend/app/services/scoring.py`, replace the entire body from `def effective_duty_spans(` through its closing `return result` (currently lines 108-201) with:

```python
def _assignment_spans(
    a: DutyAssignment,
    *,
    overrides: dict[tuple[uuid.UUID, date], DutyDayOverride],
    dismissal_ranges: dict[uuid.UUID, list[tuple[date, date]]],
) -> list[dict[str, Any]]:
    """Expand one assignment into contiguous per-effective-soldier runs,
    applying day overrides and dismissals. Shared by effective_duty_spans
    (published-only, feeds scoring) and swap_surface_duty_spans (published +
    algorithm_draft, feeds swap/cover UI only — never scoring)."""
    def _is_dismissed(day: date) -> bool:
        return any(df <= day <= dt for df, dt in dismissal_ranges.get(a.id, []))

    last_assignment_day = a.end_date - timedelta(days=1)

    def _make_span(cur: Any, run_start: date, run_end: date) -> dict[str, Any]:
        # A run only carries the assignment's real clock time on the edge
        # day(s) that match the assignment's own boundaries; a run that
        # was split off mid-assignment by an override has no wall-clock
        # time of its own, so it degrades to a full calendar day there.
        start_time = a.start_time if run_start == a.start_date else "00:00"
        end_time = a.end_time if run_end == last_assignment_day else "23:59"
        original_owner = cur == a.soldier_id
        return {
            "assignment_id": a.id,
            "soldier_id": cur,
            "duty_type_id": a.duty_type_id,
            "duty_location_id": a.duty_location_id,
            "start_date": run_start,
            # Exclusive, matching DutyAssignment/DutyShift's own convention
            # (run_end above is the run's last INCLUSIVE day).
            "end_date": run_end + timedelta(days=1),
            "start_time": start_time,
            "end_time": end_time,
            "start_at": combine_date_time(run_start, start_time),
            "end_at": combine_date_time(run_end, end_time),
            "shift_id": a.duty_shift_id,
            "is_reserve": a.is_reserve,
            "called_up_from": a.called_up_from,
            "called_up_to": a.called_up_to,
            "weapon_ineligible": a.weapon_ineligible if original_owner else False,
            "weapon_ineligible_reason": a.weapon_ineligible_reason if original_owner else None,
        }

    spans: list[dict[str, Any]] = []
    cur: object = _UNSET
    run_start: date | None = None
    run_end: date | None = None
    day = a.start_date
    while day < a.end_date:
        ov = overrides.get((a.id, day))
        if ov is not None:
            eff = ov.effective_soldier_id
        elif _is_dismissed(day):
            eff = None
        else:
            eff = a.soldier_id
        if eff == cur:
            run_end = day
        else:
            if cur not in (None, _UNSET) and run_start is not None and run_end is not None:
                spans.append(_make_span(cur, run_start, run_end))
            cur = eff
            run_start = day if eff is not None else None
            run_end = day if eff is not None else None
        day += timedelta(days=1)
    if cur not in (None, _UNSET) and run_start is not None and run_end is not None:
        spans.append(_make_span(cur, run_start, run_end))
    return spans


def _duty_spans_for_statuses(
    session: Session,
    *,
    statuses: tuple[str, ...],
    soldier_ids: set[uuid.UUID] | None,
    date_from: date | None,
    date_to: date | None,
) -> list[dict[str, Any]]:
    assignments = (
        session.execute(select(DutyAssignment).where(DutyAssignment.status.in_(statuses)))
        .scalars()
        .all()
    )
    overrides = {
        (o.duty_assignment_id, o.date): o
        for o in session.execute(select(DutyDayOverride)).scalars().all()
    }
    dismissal_ranges: dict[uuid.UUID, list[tuple[date, date]]] = {}
    for d in session.execute(select(DutyDismissal)).scalars().all():
        dismissal_ranges.setdefault(d.duty_assignment_id, []).append((d.dismissed_from, d.dismissed_to))

    spans: list[dict[str, Any]] = []
    for a in assignments:
        spans.extend(_assignment_spans(a, overrides=overrides, dismissal_ranges=dismissal_ranges))

    result: list[dict[str, Any]] = []
    for sp in spans:
        if soldier_ids is not None and sp["soldier_id"] not in soldier_ids:
            continue
        if date_from is not None and sp["end_date"] <= date_from:
            continue
        if date_to is not None and sp["start_date"] > date_to:
            continue
        result.append(sp)
    result.sort(key=lambda s: s["start_date"])
    return result


def effective_duty_spans(
    session: Session,
    *,
    soldier_ids: set[uuid.UUID] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """Published assignments expanded per day with overrides applied, then re-merged into
    contiguous runs where the effective soldier is unchanged. Degrades to the original block
    when there are no overrides; cancelled days (NULL effective) break runs and are dropped.
    Optionally filtered to soldier_ids and to spans overlapping [date_from, date_to].

    Feeds scoring/effort — MUST stay published-only. For a swap/cover-surface
    listing that also includes algorithm_draft assignments, use
    swap_surface_duty_spans instead; do not widen the statuses passed here."""
    return _duty_spans_for_statuses(
        session, statuses=("published",), soldier_ids=soldier_ids, date_from=date_from, date_to=date_to,
    )


def swap_surface_duty_spans(
    session: Session,
    *,
    soldier_ids: set[uuid.UUID] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """Same per-day effective-soldier resolution as effective_duty_spans, but
    also includes algorithm_draft assignments. For swap/cover UI display only
    (asking for or offering a swap, trade lists) — NEVER feed this into
    scoring, effort, or fairness inputs; those must stay on
    effective_duty_spans."""
    return _duty_spans_for_statuses(
        session, statuses=("published", "algorithm_draft"),
        soldier_ids=soldier_ids, date_from=date_from, date_to=date_to,
    )
```

No import changes needed — `DutyDayOverride`, `DutyDismissal`, `combine_date_time`, and `_UNSET` are already imported/defined earlier in this file.

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `pytest app/services/tests/test_scoring_swap_surfaces.py -v`
Expected: all 4 PASS.

- [ ] **Step 5: Run the full scoring test suites to check for regressions**

Run: `pytest app/services/tests/test_scoring_dismissal.py tests/unit/test_scoring_service.py tests/unit/test_scoring_reserve.py tests/integration/test_scoring_api.py app/routes/tests/test_scoring_routes.py -q`
Expected: all PASS, 0 failures (the refactor must be behavior-preserving for `effective_duty_spans`).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/scoring.py backend/app/services/tests/test_scoring_swap_surfaces.py
git commit -m "feat: add swap_surface_duty_spans (published + draft) alongside published-only effective_duty_spans"
```

---

### Task 3: `GET /assignments/effective?for_swap=true` opts into the swap-surface listing

**Files:**
- Modify: `backend/app/routes/assignments.py:131-153`
- Test: `backend/tests/integration/test_assignments_api.py`

**Interfaces:**
- Consumes: `scoring_svc.swap_surface_duty_spans` from Task 2.
- Produces: `GET /assignments/effective` gains an optional `for_swap: bool = False` query parameter. Response shape (`EffectiveDutyOut`) is unchanged. Consumed by Task 5 (frontend `listEffectiveDuties`).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_assignments_api.py` (after `test_effective_duties_default_weapon_ineligible_false`, or anywhere at module level):

```python
def test_effective_endpoint_includes_draft_only_when_for_swap(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number=f"eff_{_uid()}")
    dtype = DutyType(name=f"שמירה_{_uid()}", score_per_day=1, active=True)
    loc = DutyLocation(name=f"loc_{_uid()}", base="בסיס")
    admin_session.add_all([dtype, loc])
    admin_session.flush()
    admin_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dtype.id, duty_location_id=loc.id,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 2),
        start_time="08:00", end_time="20:00", status="algorithm_draft",
    ))
    admin_session.commit()

    default_resp = client.get(
        "/api/assignments/effective", params={"soldier_id": str(soldier.id)}, headers=auth_headers(soldier),
    )
    assert default_resp.status_code == 200
    assert default_resp.json() == []

    swap_resp = client.get(
        "/api/assignments/effective",
        params={"soldier_id": str(soldier.id), "for_swap": "true"},
        headers=auth_headers(soldier),
    )
    assert swap_resp.status_code == 200
    assert len(swap_resp.json()) == 1
    assert swap_resp.json()[0]["duty_type_name"] == dtype.name
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/integration/test_assignments_api.py::test_effective_endpoint_includes_draft_only_when_for_swap -v`
Expected: FAIL — `swap_resp.json()` is `[]` (the route doesn't know about drafts yet), so `len(...) == 1` fails.

- [ ] **Step 3: Add the query parameter**

In `backend/app/routes/assignments.py`, change (currently lines 131-144):

```python
@router.get("/effective", response_model=list[EffectiveDutyOut])
def list_effective_duties(
    soldier_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[EffectiveDutyOut]:
    s = _load_soldier(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    spans = scoring_svc.effective_duty_spans(
        session, soldier_ids={soldier_id}, date_from=date_from, date_to=date_to
    )
```

to:

```python
@router.get("/effective", response_model=list[EffectiveDutyOut])
def list_effective_duties(
    soldier_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    for_swap: bool = False,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[EffectiveDutyOut]:
    """`for_swap=true` widens the listing to include algorithm_draft duties,
    for the swap-ask/cover-trade UI only (see scoring.swap_surface_duty_spans).
    Plain callers (transparency, calendar, etc.) must never pass this."""
    s = _load_soldier(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    span_fn = scoring_svc.swap_surface_duty_spans if for_swap else scoring_svc.effective_duty_spans
    spans = span_fn(
        session, soldier_ids={soldier_id}, date_from=date_from, date_to=date_to
    )
```

(The rest of the function body — building `type_ids`, `names`, and the return list — is unchanged.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/integration/test_assignments_api.py::test_effective_endpoint_includes_draft_only_when_for_swap -v`
Expected: PASS.

- [ ] **Step 5: Run the full assignments test suite to check for regressions**

Run: `pytest tests/integration/test_assignments_api.py -q`
Expected: all PASS, 0 failures.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/assignments.py backend/tests/integration/test_assignments_api.py
git commit -m "feat: GET /assignments/effective?for_swap=true includes draft duties"
```

---

### Task 4: Lock in that `cover_offer` already accepts a draft duty as a trade offer

**Files:**
- Test: `backend/tests/unit/test_swaps.py`

**Interfaces:**
- Consumes: `svc.cover_offer` (existing, unchanged — `backend/app/services/swaps.py:1143-1189` does not validate `offered_assignment_ids` against ownership or status today).
- Produces: nothing new. This task is a regression test only, per investigation: `cover_offer` stores `offered_assignment_ids` as-is with no status/ownership gate, so a draft duty is already accepted. Do not add new validation here — that would be unrelated scope creep; the fix for item 13 is entirely in Task 6/8 (the frontend list that currently excludes drafts from what's offered).

- [ ] **Step 1: Write the test**

Add to `backend/tests/unit/test_swaps.py` (after `test_cover_offer_no_approval_notifies_both_sides`, using the same `_seed`/`_candidate` helpers already in this file):

```python
def test_cover_offer_accepts_draft_duty_in_offered_assignment_ids(admin_session):
    """The offeror's counter-offer duties are stored as-is with no ownership
    or status validation today; a draft (algorithm_draft) duty in their own
    schedule must still be offerable as a trade candidate."""
    a, b, assignment = _seed(admin_session)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason=None, actor_id=a.id, open_to_marketplace=True,
    )
    dt = DutyType(name="שמירה-swap-draft", score_per_day=1)
    loc = DutyLocation(name="עמדה-swap-draft")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    draft_assignment = DutyAssignment(
        soldier_id=b.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 20), end_date=date(2026, 6, 21), status="algorithm_draft",
    )
    admin_session.add(draft_assignment)
    admin_session.flush()

    updated = svc.cover_offer(
        admin_session, swap_id=req.id, covering_soldier_id=b.id,
        offered_assignment_ids=[draft_assignment.id],
    )

    candidate = _candidate(admin_session, updated.id, b.id)
    assert candidate is not None
    assert candidate.offered_assignment_ids == [str(draft_assignment.id)]
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `pytest tests/unit/test_swaps.py::test_cover_offer_accepts_draft_duty_in_offered_assignment_ids -v`
Expected: PASS immediately — this documents existing behavior, no source change needed. If it unexpectedly fails, stop and re-investigate `cover_offer` before continuing (the plan's premise about the current gate would be wrong).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/test_swaps.py
git commit -m "test: lock in that cover_offer accepts a draft duty in offered_assignment_ids"
```

---

### Task 5: `listEffectiveDuties` learns the `for_swap` parameter

**Files:**
- Modify: `frontend/src/api/assignments.ts:40-42`

**Interfaces:**
- Consumes: `GET /assignments/effective?for_swap=true` from Task 3.
- Produces: `listEffectiveDuties(soldierId: string, params?: { date_from?: string; date_to?: string; for_swap?: boolean }): Promise<EffectiveDuty[]>`. Consumed by Task 6 and Task 7.

- [ ] **Step 1: Update the function signature**

In `frontend/src/api/assignments.ts`, change (currently lines 40-42):

```typescript
export async function listEffectiveDuties(soldierId: string, params?: { date_from?: string; date_to?: string }): Promise<EffectiveDuty[]> {
  return (await api.get<EffectiveDuty[]>(`/assignments/effective`, { params: { soldier_id: soldierId, ...params } })).data;
}
```

to:

```typescript
export async function listEffectiveDuties(soldierId: string, params?: { date_from?: string; date_to?: string; for_swap?: boolean }): Promise<EffectiveDuty[]> {
  return (await api.get<EffectiveDuty[]>(`/assignments/effective`, { params: { soldier_id: soldierId, ...params } })).data;
}
```

- [ ] **Step 2: Typecheck**

Run: `npm run typecheck` (from `frontend/`)
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/assignments.ts
git commit -m "feat: listEffectiveDuties accepts an optional for_swap param"
```

---

### Task 6: `SwapsPage.tsx` lists draft and received-via-swap duties for ask-swap and trade

**Files:**
- Modify: `frontend/src/pages/SwapsPage.tsx:158-162`
- Test: `frontend/src/pages/SwapsPage.test.tsx`

**Interfaces:**
- Consumes: `listEffectiveDuties` from Task 5.

- [ ] **Step 1: Update the query**

In `frontend/src/pages/SwapsPage.tsx`, change (currently lines 158-162):

```typescript
  const dutiesQuery = useQuery({
    queryKey: user ? queryKeys.effectiveDuties(user.id) : ["effectiveDuties", "anonymous"],
    queryFn: () => listEffectiveDuties(user!.id).catch(() => [] as EffectiveDuty[]),
    enabled: !!user,
  });
```

to:

```typescript
  const dutiesQuery = useQuery({
    queryKey: user ? queryKeys.effectiveDuties(user.id, { for_swap: true }) : ["effectiveDuties", "anonymous"],
    queryFn: () => listEffectiveDuties(user!.id, { for_swap: true }).catch(() => [] as EffectiveDuty[]),
    enabled: !!user,
  });
```

- [ ] **Step 2: Add the test**

`frontend/src/pages/SwapsPage.test.tsx` already mocks the whole `../api/assignments` module (line 51: `vi.mock("../api/assignments", () => ({ listEffectiveDuties: vi.fn().mockResolvedValue([]) }));`) and has a `renderPage()` helper (lines 62-73) that wraps `SwapsPage` in `QueryClientProvider` + `SoldierModalProvider` + `MemoryRouter`, with the mocked `useAuth` returning `{ id: "me", ... }` (line 55). Add a new `describe` block at the end of the file, after the existing `"SwapsPage incoming tab approval columns"` block:

```typescript
describe("SwapsPage duties query", () => {
  test("fetches effective duties with for_swap so drafts and received duties are listed", async () => {
    const { listEffectiveDuties } = await import("../api/assignments");
    renderPage();
    await screen.findAllByText("Yossi");
    expect(listEffectiveDuties).toHaveBeenCalledWith("me", { for_swap: true });
  });
});
```

(`await screen.findAllByText("Yossi")` waits for the "mine" tab's initial data — including the `dutiesQuery` — to settle before asserting on the mock call.)

- [ ] **Step 3: Run the test**

Run: `npm test -- SwapsPage` (from `frontend/`)
Expected: PASS, no other `SwapsPage` tests broken.

- [ ] **Step 4: Typecheck and lint**

Run: `npm run typecheck && npm run lint` (from `frontend/`)
Expected: no errors, zero warnings.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/SwapsPage.tsx frontend/src/pages/SwapsPage.test.tsx
git commit -m "fix: SwapsPage lists draft and received-via-swap duties for ask-swap and trade offers"
```

---

### Task 7: `OfferSwapModal.tsx` includes drafts in its trade-candidate list

**Files:**
- Modify: `frontend/src/components/OfferSwapModal.tsx:69`

**Interfaces:**
- Consumes: `listEffectiveDuties` from Task 5.

No `OfferSwapModal.test.tsx` exists in this codebase today (confirmed: `frontend/src/components/` has no test file for this component), so this task is a one-line change with no test file to write or extend — verified instead by typecheck/lint plus Task 9's manual smoke check.

- [ ] **Step 1: Update the call site**

In `frontend/src/components/OfferSwapModal.tsx`, change (currently line 69):

```typescript
      listEffectiveDuties(user.id, { date_from: today }),
```

to:

```typescript
      listEffectiveDuties(user.id, { date_from: today, for_swap: true }),
```

- [ ] **Step 2: Typecheck and lint**

Run: `npm run typecheck && npm run lint` (from `frontend/`)
Expected: no errors, zero warnings.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/OfferSwapModal.tsx
git commit -m "fix: OfferSwapModal includes draft duties in its trade-candidate list"
```

---

### Task 8: `CoverOfferModal.tsx` shows a clear empty-state message in trade mode

**Files:**
- Modify: `frontend/src/components/CoverOfferModal.tsx:81-97`
- Test: `frontend/src/components/CoverOfferModal.test.tsx`

**Interfaces:**
- Consumes: `myDuties` prop (already widened by Task 6's change to `SwapsPage.tsx`, which is `CoverOfferModal`'s only caller/prop source — no new consumption here beyond what the prop already carries).

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/components/CoverOfferModal.test.tsx`:

```typescript
  it("shows a clear empty-state message in trade mode when there are no offerable duties", async () => {
    vi.spyOn(swapsApi, "checkCoverEligibility").mockResolvedValue({
      eligible: true,
      reason: null,
    });

    render(
      <CoverOfferModal
        swap={{ id: "1", duty_assignment_id: "a1" } as SwapRequest}
        myDuties={[]}
        dutyTypes={{}}
        onDone={() => {}}
        onClose={() => {}}
      />
    );

    fireEvent.click(screen.getByLabelText("הצע שיבוץ בתמורה"));

    await waitFor(() => expect(screen.getByText("אין תורנויות להצגה")).toBeInTheDocument());
  });
```

(`"הצע שיבוץ בתמורה"` is the current value of `swaps.offer_trade` in `frontend/src/i18n/he.json:916`; `"אין תורנויות להצגה"` is `swaps.no_duties` at `he.json:919`. `CoverOfferModal.test.tsx` uses the real i18n module — see its existing `import "../i18n"` and the existing test's `screen.getByText("שלח הצעה")` assertion — so these literal Hebrew strings are what actually renders, not translation keys.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm test -- CoverOfferModal` (from `frontend/`)
Expected: the new test FAILS (no empty-state message is rendered today in trade mode).

- [ ] **Step 3: Add the empty-state message**

In `frontend/src/components/CoverOfferModal.tsx`, change (currently lines 81-97):

```typescript
          {mode === "trade" && (
            <div className="space-y-1 max-h-40 overflow-y-auto border rounded p-2 dark:border-gray-600">
              <p className="text-xs text-gray-500 mb-1">{t("swaps.select_duties_to_offer")}:</p>
              {myDuties
                .filter((d) => d.assignment_id !== swap.duty_assignment_id)
                .map((d) => (
                  <label key={d.assignment_id} className="flex items-center gap-2 text-xs cursor-pointer dark:text-gray-300">
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(d.assignment_id)}
                      onChange={() => toggleDuty(d.assignment_id)}
                    />
                    <span>{dutyTypes[d.duty_type_id] ?? d.duty_type_id} — {d.start_date}</span>
                  </label>
                ))}
            </div>
          )}
```

to:

```typescript
          {mode === "trade" && (() => {
            const offerable = myDuties.filter((d) => d.assignment_id !== swap.duty_assignment_id);
            return offerable.length === 0 ? (
              <p className="text-xs text-gray-500">{t("swaps.no_duties")}</p>
            ) : (
              <div className="space-y-1 max-h-40 overflow-y-auto border rounded p-2 dark:border-gray-600">
                <p className="text-xs text-gray-500 mb-1">{t("swaps.select_duties_to_offer")}:</p>
                {offerable.map((d) => (
                  <label key={d.assignment_id} className="flex items-center gap-2 text-xs cursor-pointer dark:text-gray-300">
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(d.assignment_id)}
                      onChange={() => toggleDuty(d.assignment_id)}
                    />
                    <span>{dutyTypes[d.duty_type_id] ?? d.duty_type_id} — {d.start_date}</span>
                  </label>
                ))}
              </div>
            );
          })()}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm test -- CoverOfferModal` (from `frontend/`)
Expected: PASS, including the pre-existing `cover_blocked:overlap` test.

- [ ] **Step 5: Typecheck and lint**

Run: `npm run typecheck && npm run lint` (from `frontend/`)
Expected: no errors, zero warnings.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/CoverOfferModal.tsx frontend/src/components/CoverOfferModal.test.tsx
git commit -m "fix: CoverOfferModal shows a clear empty-state message when no duties are offerable"
```

---

### Task 9: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Backend full suite**

Run (from `backend/`, venv active): `pytest -q`
Expected: same pass/fail profile as the `dev` baseline (0 new failures — this worktree's baseline had 31/31 passing on `tests/integration/test_swaps_api.py` before this plan; re-run the full suite and compare against that baseline, not a bare "all green" assumption, in case an unrelated pre-existing failure is already present on `dev`).

- [ ] **Step 2: Frontend typecheck, lint, unit tests**

Run (from `frontend/`):
```bash
npm run typecheck
npm run lint
npm test
```
Expected: all clean, all tests passing.

- [ ] **Step 3: Manual smoke check (optional but recommended)**

Start the dev stack (`.\dev.ps1` from repo root) and, as two soldiers in the same unit:
1. Have soldier A accept a swap covering soldier B's published duty (via the existing swap flow), so B now effectively owns a day that's still `DutyAssignment.soldier_id == A`.
2. Log in as B, go to Swaps → "My duties", confirm the received duty appears and its "בקש החלפה" button works (no `not_your_duty` error).
3. If a draft assignment exists for a soldier (e.g. after running the algorithm without publishing), confirm it appears in "My duties" and is offerable in a cover/trade list, but does **not** appear in the soldier's transparency/score breakdown page.

This step has no automated assertion — it's a manual confidence check before merging, since the algorithm-draft path is easiest to verify end-to-end by eye.
