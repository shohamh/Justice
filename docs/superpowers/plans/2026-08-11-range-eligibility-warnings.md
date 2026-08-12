# Range Eligibility Warnings & Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface richer range-qualification status (last qualification done, upcoming coverage) to soldiers and duty managers/commanders, move the weapon-ineligibility warning from a top-of-calendar banner onto per-event badges, and gate the homepage אל"ל warning by real structural relevance instead of the `is_officer`/`is_career` proxy.

**Architecture:** Extend the existing `DutyEligibilityFact` / `weapon_eligibility.py` / `range_eligibility_projection.py` data layer with two new pieces of data (latest-ever qualification, and a soldier-scoped non-duty-tied status view), then thread that data through a new backend endpoint and existing frontend consumers (ProfilePage, UnifiedSoldierModal, UnitCalendar, ShiftDetailPanel's tooltip helper). The אל"ל homepage gate reuses the existing `node_in_scope`/`eligible_node_ids` structural-eligibility pattern already used by `range_exemption.py`, cached per hierarchy node with explicit invalidation on `DutyType` writes (mirroring the existing `weapon_enforcement_changed` → `recheck_assignments` precedent).

**Tech Stack:** FastAPI + SQLAlchemy (backend), React + TypeScript + react-i18next + TanStack Query (frontend), pytest (backend tests), vitest + Testing Library (frontend tests).

## Global Constraints

- Hebrew UI strings live in `frontend/src/i18n/he.json`, nested under existing feature-area objects (e.g. `range_qualification.*`, `unit_calendar.*`) — follow that file's existing nesting convention exactly (see Task 4/6).
- Dates are formatted `dd.mm.yyyy` (Israeli convention) via the existing local `formatDate` helpers already present in the touched files — do not introduce a new date-formatting utility.
- Backend test files under `backend/app/services/tests/` and `backend/tests/integration/` in this feature area run **unmarked** (no `pytestmark`) — do not add a marker decorator; this matches every sibling file in the same directory.
- No new caching/queueing infrastructure (Redis, Celery, etc.) — this codebase has none; caches are either `functools.lru_cache` or a plain in-process dict with explicit invalidation, per `docs/superpowers/specs/2026-08-11-range-eligibility-warnings-design.md`.
- Badges/actions gated to duty managers/commanders/admins use `user?.role === "admin" || user?.is_duty_manager || user?.is_commander` (frontend) — this is a **new, broader** gate than the existing `admin || is_duty_manager` pattern in `ShiftDetailPanel.tsx`, per the live-feedback ask ("shown to duty managers and commanders").

---

## Task 1: Backend — latest-qualification query + `DutyEligibilityFact` new fields

**Files:**
- Modify: `backend/app/services/weapon_eligibility.py:70-118` (add new function after `_max_qualification_valid_untils`)
- Modify: `backend/app/services/range_eligibility_projection.py` (dataclass + `project_duty_eligibility`)
- Test: `backend/app/services/tests/test_weapon_eligibility.py`
- Test: `backend/app/services/tests/test_range_eligibility_projection.py`

**Interfaces:**
- Produces: `_latest_qualification_by_soldier(session, *, soldier_ids) -> dict[uuid.UUID, tuple[str, date] | None]` in `weapon_eligibility.py`, importable by `range_eligibility_projection.py` and by Task 2's new endpoint.
- Produces: `DutyEligibilityFact.last_qualification_type: str | None` and `.last_qualification_date: date | None` — consumed by Task 2 (endpoint), Task 4 (frontend tooltip), Task 6 (calendar badge).

- [ ] **Step 1: Write the failing backend test for the new query**

Add to `backend/app/services/tests/test_weapon_eligibility.py` (near the other `_max_qualification_valid_untils`-adjacent tests — check existing imports at the top of the file for `SoldierRangeQualification`, `RangeType`, `create_soldier`, `date`, `timedelta`, and reuse them):

```python
from app.services.weapon_eligibility import _latest_qualification_by_soldier


def test_latest_qualification_by_soldier_ignores_validity_and_picks_max(app_session: Session) -> None:
    soldier = create_soldier(app_session, personal_number="latest-001")
    app_session.add_all([
        SoldierRangeQualification(
            soldier_id=soldier.id, range_type=RangeType.laser,
            valid_until=date.today() - timedelta(days=400),  # expired
        ),
        SoldierRangeQualification(
            soldier_id=soldier.id, range_type=RangeType.live,
            valid_until=date.today() - timedelta(days=10),  # expired, but most recent
        ),
    ])
    app_session.commit()

    result = _latest_qualification_by_soldier(app_session, soldier_ids=[soldier.id])

    assert result[soldier.id] == (RangeType.live, date.today() - timedelta(days=10))


def test_latest_qualification_by_soldier_returns_none_for_soldier_with_no_rows(app_session: Session) -> None:
    soldier = create_soldier(app_session, personal_number="latest-002")
    app_session.commit()

    result = _latest_qualification_by_soldier(app_session, soldier_ids=[soldier.id])

    assert result[soldier.id] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/app/services/tests/test_weapon_eligibility.py -k latest_qualification -v`
Expected: FAIL with `ImportError: cannot import name '_latest_qualification_by_soldier'`

- [ ] **Step 3: Implement `_latest_qualification_by_soldier`**

Insert into `backend/app/services/weapon_eligibility.py` immediately after `_max_qualification_valid_untils` (after line 118, before `_future_windows_by_soldier_and_required_type` at line 121):

```python
def _latest_qualification_by_soldier(
    session: Session,
    *,
    soldier_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, tuple[str, date] | None]:
    """Most recent SoldierRangeQualification per soldier, regardless of validity.

    Unlike `_max_qualification_valid_untils`, this does NOT filter by tier or
    exclude expired rows — it answers "what's the last range this soldier ever
    did at all," used to enrich the "no valid qualification" explanation with
    "last done: <type> on <date>" instead of a bare negative.
    """
    unique_soldier_ids = set(soldier_ids)
    if not unique_soldier_ids:
        return {}
    from app.db.models import SoldierRangeQualification

    latest: dict[uuid.UUID, tuple[str, date]] = {}
    for soldier_id, range_type, valid_until in session.execute(
        select(
            SoldierRangeQualification.soldier_id,
            SoldierRangeQualification.range_type,
            SoldierRangeQualification.valid_until,
        ).where(SoldierRangeQualification.soldier_id.in_(unique_soldier_ids))
    ).all():
        previous = latest.get(soldier_id)
        if previous is None or valid_until > previous[1]:
            latest[soldier_id] = (range_type, valid_until)

    return {soldier_id: latest.get(soldier_id) for soldier_id in unique_soldier_ids}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/app/services/tests/test_weapon_eligibility.py -k latest_qualification -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Write the failing test for the new `DutyEligibilityFact` fields**

Add to `backend/app/services/tests/test_range_eligibility_projection.py` (reuse the file's existing imports/fixtures/helpers for building a soldier + duty type + duty assignment — check the top of the file for its local `_duty_type`/`_duty` helpers and mirror their signatures):

```python
def test_project_duty_eligibility_includes_last_qualification_when_ineligible(app_session: Session) -> None:
    soldier = create_soldier(app_session, personal_number="proj-last-001")
    _enable_mitvachim(app_session)
    duty_type = _duty_type(app_session, required_range_type=RangeType.alal)
    duty = _duty(app_session, soldier=soldier, duty_type=duty_type, start_date=date.today() + timedelta(days=5))
    app_session.add(SoldierRangeQualification(
        soldier_id=soldier.id, range_type=RangeType.laser,
        valid_until=date.today() - timedelta(days=100),
    ))
    app_session.commit()

    facts = project_duty_eligibility(
        app_session, soldier_ids=[soldier.id], duty_ids=[duty.id], as_of=date.today(),
    )
    fact = facts[soldier.id, duty.id]

    assert fact.eligible is False
    assert fact.last_qualification_type == RangeType.laser
    assert fact.last_qualification_date == date.today() - timedelta(days=100)


def test_project_duty_eligibility_last_qualification_none_when_never_qualified(app_session: Session) -> None:
    soldier = create_soldier(app_session, personal_number="proj-last-002")
    _enable_mitvachim(app_session)
    duty_type = _duty_type(app_session, required_range_type=RangeType.alal)
    duty = _duty(app_session, soldier=soldier, duty_type=duty_type, start_date=date.today() + timedelta(days=5))
    app_session.commit()

    facts = project_duty_eligibility(
        app_session, soldier_ids=[soldier.id], duty_ids=[duty.id], as_of=date.today(),
    )
    fact = facts[soldier.id, duty.id]

    assert fact.last_qualification_type is None
    assert fact.last_qualification_date is None
```

(If the file's existing helper names differ from `_duty_type`/`_duty`/`_enable_mitvachim`, use the actual names found at the top of `test_range_eligibility_projection.py` — do not invent new ones.)

- [ ] **Step 6: Run tests to verify they fail**

Run: `pytest backend/app/services/tests/test_range_eligibility_projection.py -k last_qualification -v`
Expected: FAIL with `TypeError` (unexpected keyword / AttributeError on `.last_qualification_type`)

- [ ] **Step 7: Add the two fields to `DutyEligibilityFact` and wire them into `project_duty_eligibility`**

In `backend/app/services/range_eligibility_projection.py`:

Update the import (line 15-21) to add `_latest_qualification_by_soldier`:

```python
from app.services.weapon_eligibility import (
    _enforce_enabled,
    _future_windows_by_soldier_and_required_type,
    _is_eligible_from_data,
    _latest_qualification_by_soldier,
    _max_qualification_valid_untils,
    _pending_excusal_disqualifies,
)
```

Update the dataclass (lines 24-32):

```python
@dataclass(frozen=True)
class DutyEligibilityFact:
    eligible: bool
    required_range_type: str | None
    qualification_source: str | None
    covered_by_range_date: date | None
    covering_range_type: str | None
    projected_valid_until: date | None
    reason: str | None
    last_qualification_type: str | None
    last_qualification_date: date | None
```

In `project_duty_eligibility`, after computing `future_windows` (after line 123), add:

```python
    latest_qualifications = _latest_qualification_by_soldier(
        session, soldier_ids=list(projected_soldier_ids),
    )
```

Update the `enforcement_disabled` early-return branch (lines 94-105) to include the new fields:

```python
    if not _enforce_enabled(session):
        return {
            (requirement.soldier_id, duty_id): DutyEligibilityFact(
                eligible=True,
                required_range_type=requirement.required_range_type,
                qualification_source="enforcement_disabled",
                covered_by_range_date=None,
                covering_range_type=None,
                projected_valid_until=None,
                reason=None,
                last_qualification_type=None,
                last_qualification_date=None,
            )
            for duty_id, requirement in requirements.items()
        }
```

Update the `not_required` branch (lines 130-138):

```python
        if required_range_type is None:
            facts[soldier_id, duty_id] = DutyEligibilityFact(
                eligible=True,
                required_range_type=None,
                qualification_source="not_required",
                covered_by_range_date=None,
                covering_range_type=None,
                projected_valid_until=None,
                reason=None,
                last_qualification_type=None,
                last_qualification_date=None,
            )
            continue
```

Update the final fact construction (lines 164-172):

```python
        latest = latest_qualifications.get(soldier_id)
        facts[soldier_id, duty_id] = DutyEligibilityFact(
            eligible=eligible,
            required_range_type=required_range_type,
            qualification_source=qualification_source,
            covered_by_range_date=covered_by_range_date,
            covering_range_type=covering_range_type,
            projected_valid_until=projected_valid_until,
            reason=None if eligible else "weapon_qualification",
            last_qualification_type=latest[0] if latest else None,
            last_qualification_date=latest[1] if latest else None,
        )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest backend/app/services/tests/test_range_eligibility_projection.py backend/app/services/tests/test_ineligible_soldiers.py -v`
Expected: PASS (existing tests still pass since the new fields are additive; `test_ineligible_soldiers.py` exercises `project_duty_eligibility` transitively and must not break on the new dataclass fields — if any existing test constructs a `DutyEligibilityFact(...)` directly by positional/keyword args without the two new fields, update it to pass them explicitly)

- [ ] **Step 9: Update the route schema that flattens `DutyEligibilityFact`**

In `backend/app/routes/range_qualification_visibility.py`, add the two fields to `UpcomingWeaponDutyOut` (lines 36-48) and to its construction in `_soldier_out` (lines 151-166):

```python
class UpcomingWeaponDutyOut(BaseModel):
    assignment_id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_type_name: str
    start_date: date_type
    end_date: date_type
    required_range_type: RangeType
    eligible: bool
    qualification_source: str | None
    covered_by_range_date: date_type | None
    covering_range_type: RangeType | None
    projected_valid_until: date_type | None
    reason: str | None
    last_qualification_type: RangeType | None
    last_qualification_date: date_type | None
```

```python
        upcoming_weapon_duties=[
            UpcomingWeaponDutyOut(
                assignment_id=duty.assignment_id,
                duty_type_id=duty.duty_type_id,
                duty_type_name=duty.duty_type_name,
                start_date=duty.start_date,
                end_date=duty.end_date,
                required_range_type=duty.required_range_type,
                eligible=record.duty_eligibility[duty.assignment_id].eligible,
                qualification_source=record.duty_eligibility[duty.assignment_id].qualification_source,
                covered_by_range_date=record.duty_eligibility[duty.assignment_id].covered_by_range_date,
                covering_range_type=record.duty_eligibility[duty.assignment_id].covering_range_type,
                projected_valid_until=record.duty_eligibility[duty.assignment_id].projected_valid_until,
                reason=record.duty_eligibility[duty.assignment_id].reason,
                last_qualification_type=record.duty_eligibility[duty.assignment_id].last_qualification_type,
                last_qualification_date=record.duty_eligibility[duty.assignment_id].last_qualification_date,
            )
            for duty in record.upcoming_weapon_duties
        ],
```

- [ ] **Step 10: Run the full ineligible-soldiers integration test to verify no regression**

Run: `pytest backend/tests/integration/test_ineligible_soldiers_api.py -v`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add backend/app/services/weapon_eligibility.py backend/app/services/range_eligibility_projection.py backend/app/routes/range_qualification_visibility.py backend/app/services/tests/test_weapon_eligibility.py backend/app/services/tests/test_range_eligibility_projection.py
git commit -m "feat: add last-qualification-ever tracking to DutyEligibilityFact"
```

---

## Task 2: Backend — soldier-scoped range-status endpoint (item 7)

**Files:**
- Create: `backend/app/services/soldier_range_status.py`
- Modify: `backend/app/routes/range_qualification_visibility.py` (add route + schemas)
- Test: `backend/app/services/tests/test_soldier_range_status.py`
- Test: `backend/tests/integration/test_soldier_range_status_api.py`

**Interfaces:**
- Consumes: `_max_qualification_valid_untils`, `_future_windows_by_soldier_and_required_type`, `_latest_qualification_by_soldier`, `_pending_excusal_disqualifies`, `_enforce_enabled` from `weapon_eligibility.py` (Task 1); `node_in_scope` from `app.algorithm.types`.
- Produces: `list_relevant_range_statuses(session, *, soldier) -> list[RangeStatus]` where `RangeStatus` is a frozen dataclass with fields `required_range_type, eligible, qualification_source, covered_by_range_date, covering_range_type, projected_valid_until, last_qualification_type, last_qualification_date` — consumed by the route handler in this task.

- [ ] **Step 1: Write the failing service-level test**

Create `backend/app/services/tests/test_soldier_range_status.py`:

```python
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.db.models import DutyType, RangeType, SoldierRangeQualification
from app.services.settings_loader import set_setting
from app.services.soldier_range_status import list_relevant_range_statuses
from tests.helpers import create_node, create_soldier


def _enable_mitvachim(session: Session) -> None:
    set_setting(session, "mitvachim.enabled", True, actor_id=None)


def test_returns_one_status_per_relevant_required_range_type(app_session: Session) -> None:
    node = create_node(app_session, level="team", name="range-status-team-1")
    soldier = create_soldier(app_session, personal_number="rs-001", hierarchy_node_id=node.id)
    _enable_mitvachim(app_session)
    app_session.add(DutyType(
        name="alal-duty-1", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    ))
    app_session.commit()

    statuses = list_relevant_range_statuses(app_session, soldier=soldier)

    assert len(statuses) == 1
    assert statuses[0].required_range_type == RangeType.alal
    assert statuses[0].eligible is False
    assert statuses[0].last_qualification_type is None


def test_reports_current_qualification_as_eligible(app_session: Session) -> None:
    node = create_node(app_session, level="team", name="range-status-team-2")
    soldier = create_soldier(app_session, personal_number="rs-002", hierarchy_node_id=node.id)
    _enable_mitvachim(app_session)
    app_session.add(DutyType(
        name="alal-duty-2", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    ))
    app_session.add(SoldierRangeQualification(
        soldier_id=soldier.id, range_type=RangeType.alal,
        valid_until=date.today() + timedelta(days=30),
    ))
    app_session.commit()

    statuses = list_relevant_range_statuses(app_session, soldier=soldier)

    assert statuses[0].eligible is True
    assert statuses[0].qualification_source == "current_qualification"


def test_returns_empty_when_soldier_has_no_relevant_duty_types(app_session: Session) -> None:
    node = create_node(app_session, level="team", name="range-status-team-3")
    soldier = create_soldier(app_session, personal_number="rs-003", hierarchy_node_id=node.id)
    _enable_mitvachim(app_session)
    app_session.commit()

    statuses = list_relevant_range_statuses(app_session, soldier=soldier)

    assert statuses == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/app/services/tests/test_soldier_range_status.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.soldier_range_status'`

- [ ] **Step 3: Implement `soldier_range_status.py`**

Create `backend/app/services/soldier_range_status.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithm.types import node_in_scope
from app.db.models import DutyType, HierarchyNode, Soldier
from app.services.weapon_eligibility import (
    _enforce_enabled,
    _future_windows_by_soldier_and_required_type,
    _is_eligible_from_data,
    _latest_qualification_by_soldier,
    _max_qualification_valid_untils,
    _pending_excusal_disqualifies,
)


@dataclass(frozen=True)
class RangeStatus:
    required_range_type: str
    eligible: bool
    qualification_source: str | None
    covered_by_range_date: date | None
    covering_range_type: str | None
    projected_valid_until: date | None
    last_qualification_type: str | None
    last_qualification_date: date | None


def _relevant_required_range_types(session: Session, *, soldier: Soldier) -> set[str]:
    """required_range_type tiers structurally reachable by this soldier's node,
    independent of any specific scheduled duty. Mirrors the structural-eligibility
    pattern in range_exemption.py's _has_any_eligible_weapon_duty_type."""
    if soldier.hierarchy_node_id is None:
        return set()
    node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if node is None:
        return set()
    duty_types = session.execute(
        select(DutyType).where(
            DutyType.required_range_type.is_not(None), DutyType.active.is_(True),
        )
    ).scalars().all()
    return {
        duty_type.required_range_type
        for duty_type in duty_types
        if node_in_scope(duty_type.eligible_node_ids, node.path_ids)
    }


def list_relevant_range_statuses(session: Session, *, soldier: Soldier) -> list[RangeStatus]:
    """Range-qualification status for a soldier, independent of any specific duty —
    "as of today," one entry per required_range_type tier relevant to their node."""
    required_types = _relevant_required_range_types(session, soldier=soldier)
    if not required_types:
        return []

    as_of = date.today()
    latest_qualifications = _latest_qualification_by_soldier(session, soldier_ids=[soldier.id])
    latest = latest_qualifications.get(soldier.id)

    if not _enforce_enabled(session):
        return [
            RangeStatus(
                required_range_type=required_type,
                eligible=True,
                qualification_source="enforcement_disabled",
                covered_by_range_date=None,
                covering_range_type=None,
                projected_valid_until=None,
                last_qualification_type=latest[0] if latest else None,
                last_qualification_date=latest[1] if latest else None,
            )
            for required_type in sorted(required_types)
        ]

    valid_untils = _max_qualification_valid_untils(
        session, soldier_ids=[soldier.id], required_range_types=list(required_types),
    )
    future_windows = _future_windows_by_soldier_and_required_type(
        session,
        soldier_ids=[soldier.id],
        required_range_types=list(required_types),
        disqualify_pending=_pending_excusal_disqualifies(session),
        future_start=as_of,
    )

    statuses: list[RangeStatus] = []
    for required_type in sorted(required_types):
        current_valid_until = valid_untils[soldier.id, required_type]
        windows = future_windows[soldier.id, required_type]
        eligible = _is_eligible_from_data(
            current_best_valid_until=current_valid_until, future_windows=windows, as_of=as_of,
        )
        matching_window = next(
            (window for window in windows if window[0] <= as_of <= window[1]), None,
        )
        if current_valid_until is not None and current_valid_until >= as_of:
            qualification_source = "current_qualification"
            covered_by_range_date = None
            covering_range_type = None
            projected_valid_until = current_valid_until
        elif matching_window is not None:
            qualification_source = "planned_range"
            covered_by_range_date, projected_valid_until, covering_range_type = matching_window
        else:
            qualification_source = None
            covered_by_range_date = None
            covering_range_type = None
            projected_valid_until = None
        statuses.append(RangeStatus(
            required_range_type=required_type,
            eligible=eligible,
            qualification_source=qualification_source,
            covered_by_range_date=covered_by_range_date,
            covering_range_type=covering_range_type,
            projected_valid_until=projected_valid_until,
            last_qualification_type=latest[0] if latest else None,
            last_qualification_date=latest[1] if latest else None,
        ))
    return statuses
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/app/services/tests/test_soldier_range_status.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Write the failing route/integration test**

Create `backend/tests/integration/test_soldier_range_status_api.py`:

```python
from __future__ import annotations

from datetime import date, timedelta

from app.db.models import DutyManagerScope, DutyType, RangeType
from app.services.settings_loader import set_setting
from tests.helpers import auth_headers, create_node, create_soldier


def _enable_mitvachim(session) -> None:
    set_setting(session, "mitvachim.enabled", True, actor_id=None)


def test_self_can_view_own_range_status(client, admin_session) -> None:
    node = create_node(admin_session, level="team", name="rs-api-team-1")
    soldier = create_soldier(admin_session, personal_number="rs-api-001", hierarchy_node_id=node.id)
    _enable_mitvachim(admin_session)
    admin_session.add(DutyType(
        name="rs-api-duty-1", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    ))
    admin_session.commit()

    response = client.get(f"/api/soldiers/{soldier.id}/range-status", headers=auth_headers(soldier))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["soldier_id"] == str(soldier.id)
    assert body["statuses"][0]["required_range_type"] == "alal"
    assert body["statuses"][0]["eligible"] is False


def test_out_of_scope_soldier_gets_403(client, admin_session) -> None:
    node = create_node(admin_session, level="team", name="rs-api-team-2")
    other_node = create_node(admin_session, level="team", name="rs-api-team-3")
    target = create_soldier(admin_session, personal_number="rs-api-002", hierarchy_node_id=node.id)
    other_soldier = create_soldier(admin_session, personal_number="rs-api-003", hierarchy_node_id=other_node.id)
    admin_session.commit()

    response = client.get(f"/api/soldiers/{target.id}/range-status", headers=auth_headers(other_soldier))

    assert response.status_code == 403


def test_duty_manager_in_scope_can_view(client, admin_session) -> None:
    node = create_node(admin_session, level="team", name="rs-api-team-4")
    target = create_soldier(admin_session, personal_number="rs-api-004", hierarchy_node_id=node.id)
    duty_manager = create_soldier(admin_session, personal_number="rs-api-005", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=duty_manager.id, hierarchy_node_id=node.id))
    admin_session.commit()

    response = client.get(f"/api/soldiers/{target.id}/range-status", headers=auth_headers(duty_manager))

    assert response.status_code == 200, response.text
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest backend/tests/integration/test_soldier_range_status_api.py -v`
Expected: FAIL with 404 (route doesn't exist yet)

- [ ] **Step 7: Add the route**

In `backend/app/routes/range_qualification_visibility.py`, add these imports near the top (after existing imports, before `router = APIRouter(...)`):

```python
from app.auth.authz import Action, authorize
from app.services.soldier_range_status import list_relevant_range_statuses
```

Add these schemas after `IneligibleSoldierCountOut` (after line 79):

```python
class RangeStatusOut(BaseModel):
    required_range_type: RangeType
    eligible: bool
    qualification_source: str | None
    covered_by_range_date: date_type | None
    covering_range_type: RangeType | None
    projected_valid_until: date_type | None
    last_qualification_type: RangeType | None
    last_qualification_date: date_type | None


class SoldierRangeStatusOut(BaseModel):
    soldier_id: uuid.UUID
    statuses: list[RangeStatusOut]
```

Add the route after `list_ineligible_soldiers` (after line 236, using a `/soldiers` prefix separate from this router's `/ranges` prefix — declare a second router since `soldiers/{id}/range-status` doesn't share this file's `/ranges` prefix):

```python
soldiers_router = APIRouter(prefix="/soldiers", tags=["ranges"])


@soldiers_router.get("/{soldier_id}/range-status", response_model=SoldierRangeStatusOut)
def get_soldier_range_status(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SoldierRangeStatusOut:
    target = session.get(Soldier, soldier_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    is_self = target.id == user.id
    if not is_self and user.role != "admin":
        target_node = (
            session.get(HierarchyNode, target.hierarchy_node_id)
            if target.hierarchy_node_id
            else None
        )
        authorize(session, user, Action.SOLDIER_READ, target_node=target_node)
    statuses = list_relevant_range_statuses(session, soldier=target)
    return SoldierRangeStatusOut(
        soldier_id=target.id,
        statuses=[
            RangeStatusOut(
                required_range_type=s.required_range_type,
                eligible=s.eligible,
                qualification_source=s.qualification_source,
                covered_by_range_date=s.covered_by_range_date,
                covering_range_type=s.covering_range_type,
                projected_valid_until=s.projected_valid_until,
                last_qualification_type=s.last_qualification_type,
                last_qualification_date=s.last_qualification_date,
            )
            for s in statuses
        ],
    )
```

(This mirrors the exact `is_self` / `authorize(..., Action.SOLDIER_READ, ...)` pattern already used by `get_soldier` in `backend/app/routes/soldiers.py:564-590` — confirm `Action.SOLDIER_READ` exists in `app.auth.authz` before using it; if the enum member has a different name, use the actual one found there.)

- [ ] **Step 8: Register the new router**

Find where `range_qualification_visibility.router` is included (search `backend/app/main.py` or wherever routers are registered — likely `app.include_router(range_qualification_visibility.router, ...)`), and add a second include line for `soldiers_router`:

```python
app.include_router(range_qualification_visibility.soldiers_router, prefix="/api")
```

(Match the exact `prefix="/api"` / dependency pattern already used for the existing `range_qualification_visibility.router` include line.)

- [ ] **Step 9: Run tests to verify they pass**

Run: `pytest backend/tests/integration/test_soldier_range_status_api.py -v`
Expected: PASS (3 tests)

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/soldier_range_status.py backend/app/routes/range_qualification_visibility.py backend/app/main.py backend/app/services/tests/test_soldier_range_status.py backend/tests/integration/test_soldier_range_status_api.py
git commit -m "feat: add soldier-scoped range-status endpoint"
```

---

## Task 3: Backend — אל"ל structural relevance + cache + `/me` wiring

**Files:**
- Create: `backend/app/services/alal_relevance.py`
- Modify: `backend/app/routes/duty_config.py` (invalidation hooks on DutyType create/update/delete)
- Modify: `backend/app/routes/me.py` (add `alal_relevant` field)
- Test: `backend/app/services/tests/test_alal_relevance.py`

**Interfaces:**
- Produces: `is_alal_relevant(session, soldier) -> bool` and `invalidate_alal_relevance_cache() -> None`, both importable from `app.services.alal_relevance` — consumed by `routes/me.py` (this task) and `routes/duty_config.py` (this task).

- [ ] **Step 1: Write the failing test**

Create `backend/app/services/tests/test_alal_relevance.py`:

```python
from __future__ import annotations

from app.db.models import DutyType, RangeType
from app.services.alal_relevance import invalidate_alal_relevance_cache, is_alal_relevant
from tests.helpers import create_node, create_soldier


def test_soldier_in_scope_of_alal_duty_type_is_relevant(app_session) -> None:
    node = create_node(app_session, level="team", name="alal-rel-team-1")
    soldier = create_soldier(app_session, personal_number="alal-rel-001", hierarchy_node_id=node.id)
    app_session.add(DutyType(
        name="alal-rel-duty-1", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    ))
    app_session.commit()
    invalidate_alal_relevance_cache()

    assert is_alal_relevant(app_session, soldier) is True


def test_soldier_with_only_non_alal_duty_types_is_not_relevant(app_session) -> None:
    node = create_node(app_session, level="team", name="alal-rel-team-2")
    soldier = create_soldier(app_session, personal_number="alal-rel-002", hierarchy_node_id=node.id)
    app_session.add(DutyType(
        name="alal-rel-duty-2", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.laser, eligible_node_ids=[node.id],
    ))
    app_session.commit()
    invalidate_alal_relevance_cache()

    assert is_alal_relevant(app_session, soldier) is False


def test_soldier_with_no_hierarchy_node_is_not_relevant(app_session) -> None:
    soldier = create_soldier(app_session, personal_number="alal-rel-003", hierarchy_node_id=None)
    app_session.commit()
    invalidate_alal_relevance_cache()

    assert is_alal_relevant(app_session, soldier) is False


def test_cache_reflects_new_duty_type_only_after_invalidation(app_session) -> None:
    node = create_node(app_session, level="team", name="alal-rel-team-4")
    soldier = create_soldier(app_session, personal_number="alal-rel-004", hierarchy_node_id=node.id)
    app_session.commit()
    invalidate_alal_relevance_cache()

    assert is_alal_relevant(app_session, soldier) is False

    app_session.add(DutyType(
        name="alal-rel-duty-4", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    ))
    app_session.commit()

    assert is_alal_relevant(app_session, soldier) is False  # stale cache, not yet invalidated
    invalidate_alal_relevance_cache()
    assert is_alal_relevant(app_session, soldier) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/app/services/tests/test_alal_relevance.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.alal_relevance'`

- [ ] **Step 3: Implement `alal_relevance.py`**

Create `backend/app/services/alal_relevance.py`:

```python
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithm.types import node_in_scope
from app.db.models import DutyType, HierarchyNode, RangeType, Soldier

_cache: dict[uuid.UUID, bool] = {}


def invalidate_alal_relevance_cache() -> None:
    """Call after any write that could change which nodes are אל"ל-relevant:
    DutyType create/update/delete. Mirrors the invalidate-on-write pattern used
    for the DutyAssignment.weapon_ineligible cache columns (duty_eligibility_watch.py)."""
    _cache.clear()


def _node_is_alal_relevant(session: Session, *, node: HierarchyNode) -> bool:
    alal_duty_types = session.execute(
        select(DutyType).where(
            DutyType.required_range_type == RangeType.alal, DutyType.active.is_(True),
        )
    ).scalars().all()
    return any(
        node_in_scope(duty_type.eligible_node_ids, node.path_ids) for duty_type in alal_duty_types
    )


def is_alal_relevant(session: Session, soldier: Soldier) -> bool:
    """True iff soldier's hierarchy node is structurally in scope for any active
    DutyType requiring required_range_type == alal. Cached per hierarchy_node_id
    (far fewer distinct nodes than soldiers); invalidated explicitly on DutyType
    writes rather than TTL'd, since duty-type config changes rarely."""
    if soldier.hierarchy_node_id is None:
        return False
    if soldier.hierarchy_node_id in _cache:
        return _cache[soldier.hierarchy_node_id]
    node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if node is None:
        _cache[soldier.hierarchy_node_id] = False
        return False
    result = _node_is_alal_relevant(session, node=node)
    _cache[soldier.hierarchy_node_id] = result
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/app/services/tests/test_alal_relevance.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Wire invalidation into DutyType write paths**

In `backend/app/routes/duty_config.py`, add the import near the top:

```python
from app.services.alal_relevance import invalidate_alal_relevance_cache
```

At the end of `create_duty_type` (line 147 area), `update_duty_type` (line 179 area — after its existing `session.commit()`, alongside its existing weapon-eligibility recheck hook at lines 221-231), and `delete_duty_type` (line 286 area, after `session.delete(dt)` / commit), add a call to `invalidate_alal_relevance_cache()`. Concretely, in `update_duty_type`, place it right after the existing `session.commit()` that follows the lines-221-231 recheck block so it fires on every update regardless of whether `required_range_type` changed (a change to `eligible_node_ids` alone must also invalidate):

```python
    invalidate_alal_relevance_cache()
```

Do this at the equivalent post-commit point in `create_duty_type` and `delete_duty_type` too.

- [ ] **Step 6: Write the failing test for `/me` wiring**

Find `backend/app/routes/me.py`'s existing test file (search `backend/tests/integration/` for a `test_me*.py` file — read it to find its exact request/assertion pattern) and add:

```python
def test_me_includes_alal_relevant_flag(client, admin_session) -> None:
    node = create_node(admin_session, level="team", name="me-alal-team")
    soldier = create_soldier(admin_session, personal_number="me-alal-001", hierarchy_node_id=node.id)
    admin_session.add(DutyType(
        name="me-alal-duty", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    ))
    admin_session.commit()

    response = client.get("/api/me", headers=auth_headers(soldier))

    assert response.status_code == 200, response.text
    assert response.json()["alal_relevant"] is True
```

(Adapt the `client`/auth-header setup to match whatever fixtures the existing `test_me*.py` file already uses — read it first rather than assuming `client`/`admin_session`/`auth_headers` if it uses different names.)

- [ ] **Step 7: Run test to verify it fails**

Run: `pytest backend/tests/integration/ -k me_includes_alal -v`
Expected: FAIL with `KeyError: 'alal_relevant'`

- [ ] **Step 8: Add `alal_relevant` to `MeResponse` and the `me()` handler**

In `backend/app/routes/me.py`, add `alal_relevant: bool` to the `MeResponse` schema (in the 22-53 field block, alongside `is_officer`/`is_career`), and in the `me()` handler (lines 114-146), add:

```python
    from app.services.alal_relevance import is_alal_relevant
    ...
    alal_relevant=is_alal_relevant(session, user),
```

passed into the `MeResponse(...)` construction alongside the other fields (match whatever local variable name the handler already uses for the session and the current soldier — read the handler body first to place this correctly rather than guessing the exact variable names).

- [ ] **Step 9: Run tests to verify they pass**

Run: `pytest backend/tests/integration/ -k me_includes_alal -v`
Expected: PASS

- [ ] **Step 10: Run the full duty_config and duty_eligibility_watch test suites to check for regressions**

Run: `pytest backend/app/services/tests/test_duty_config.py backend/app/services/tests/test_duty_eligibility_watch.py backend/app/services/tests/test_duty_eligibility_watch_broad_triggers.py -v`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add backend/app/services/alal_relevance.py backend/app/routes/duty_config.py backend/app/routes/me.py backend/app/services/tests/test_alal_relevance.py
git commit -m "feat: gate homepage alal warning by structural duty-type relevance"
```

---

## Task 4: Frontend — extend `DutyEligibilityFact` type + richer explanation text

**Files:**
- Modify: `frontend/src/api/ineligibleSoldiers.ts:19-29`
- Modify: `frontend/src/utils/rangeEligibilityExplanation.ts`
- Modify: `frontend/src/i18n/he.json` (lines ~1368-1373, `range_qualification.explanation`)
- Test: `frontend/src/utils/rangeEligibilityExplanation.test.ts`

**Interfaces:**
- Consumes: backend `last_qualification_type`/`last_qualification_date` fields added to the API response in Task 1.
- Produces: `DutyEligibilityFact` TS interface with the two new optional fields — consumed by Task 5 (ProfilePage/modal), Task 6 (calendar badges).

- [ ] **Step 1: Add the fields to the TS interface**

In `frontend/src/api/ineligibleSoldiers.ts`, update `DutyEligibilityFact` (lines 19-29):

```typescript
export interface DutyEligibilityFact {
  eligible: boolean;
  required_range_type: RangeType | null;
  qualification_source: string | null;
  covered_by_range_date: string | null;
  covering_range_type: RangeType | null;
  projected_valid_until: string | null;
  reason: string | null;
  duty_type_name: string;
  start_date: string;
  last_qualification_type: RangeType | null;
  last_qualification_date: string | null;
}
```

- [ ] **Step 2: Write the failing test for the richer explanation**

Add to `frontend/src/utils/rangeEligibilityExplanation.test.ts` (reuse the file's existing `fact()` builder helper and fake-`t` setup — read the top of the file first for the exact helper signature):

```typescript
it("appends the last qualification when uncovered and previously qualified", () => {
  const result = formatRangeEligibilityExplanation(
    fact({
      qualification_source: null,
      last_qualification_type: "laser",
      last_qualification_date: "2026-03-01",
    }),
    t,
  );
  expect(result).toContain("מטווח אחרון");
});

it("notes never-qualified when uncovered and no last qualification exists", () => {
  const result = formatRangeEligibilityExplanation(
    fact({ qualification_source: null, last_qualification_type: null, last_qualification_date: null }),
    t,
  );
  expect(result).toContain("אין מטווחים בתוקף");
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npm test -- rangeEligibilityExplanation` (from `frontend/`)
Expected: FAIL (the fake `t` throws or returns the raw key for the two new translation keys, since they don't exist yet; `toContain` assertions fail)

- [ ] **Step 4: Add the i18n keys**

In `frontend/src/i18n/he.json`, inside `range_qualification.explanation` (lines 1368-1373), add two new sibling keys:

```json
    "explanation": {
      "noCurrentQualification": "אין מטווחים בתוקף",
      "noWeaponDuty": "טרם שובץ לתורנות שדורשת נשק",
      "uncoveredDuty": "משובץ לתורנות {{dutyType}} שדורשת לפחות מטווח מסוג {{rangeType}} בתאריך {{date}}",
      "plannedRangeCoverage": "מטווח מתוכנן מסוג {{rangeType}} בתאריך {{rangeDate}} מכסה את התורנות; הכשירות צפויה בתוקף עד {{projectedValidUntil}}",
      "neverQualified": "אין מטווחים בתוקף",
      "lastQualification": "מטווח אחרון - {{rangeType}} ב{{date}}"
    },
```

- [ ] **Step 5: Update `formatRangeEligibilityExplanation` to append the last-qualification clause**

In `frontend/src/utils/rangeEligibilityExplanation.ts`, replace the final `uncoveredDuty` branch (lines 33-37):

```typescript
  const lastQualificationClause = fact.last_qualification_date
    ? t("range_qualification.explanation.lastQualification", {
        rangeType: RANGE_TYPE_LABELS[fact.last_qualification_type ?? ""] ?? fact.last_qualification_type,
        date: formatDate(fact.last_qualification_date),
      })
    : t("range_qualification.explanation.neverQualified");

  return `${t("range_qualification.explanation.uncoveredDuty", {
    dutyType: fact.duty_type_name,
    rangeType: RANGE_TYPE_LABELS[fact.required_range_type] ?? fact.required_range_type,
    date: formatDate(fact.start_date),
  })} ${lastQualificationClause}`;
```

- [ ] **Step 6: Run test to verify it passes**

Run: `npm test -- rangeEligibilityExplanation` (from `frontend/`)
Expected: PASS

- [ ] **Step 7: Run the i18n completeness test**

Run: `npm test -- i18n/he.test` (from `frontend/`)
Expected: PASS (new keys are present, nothing orphaned)

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/ineligibleSoldiers.ts frontend/src/utils/rangeEligibilityExplanation.ts frontend/src/i18n/he.json frontend/src/utils/rangeEligibilityExplanation.test.ts
git commit -m "feat: enrich uncovered-duty explanation with last qualification done"
```

---

## Task 5: Frontend — item 7: range-status section on ProfilePage & UnifiedSoldierModal

**Files:**
- Create: `frontend/src/api/rangeStatus.ts`
- Test: `frontend/src/api/rangeStatus.test.ts`
- Modify: `frontend/src/pages/ProfilePage.tsx` (insert section after line 266)
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx` (insert into "profile" tab block, after line 382)
- Modify: `frontend/src/i18n/he.json` (new `range_qualification.status.*` keys)

**Interfaces:**
- Consumes: `DutyEligibilityFact`-shaped statuses from `GET /soldiers/{id}/range-status` (Task 2); `formatRangeEligibilityExplanation` (Task 4).
- Produces: `getSoldierRangeStatus(soldierId: string): Promise<SoldierRangeStatusResponse>` from `api/rangeStatus.ts`.

- [ ] **Step 1: Write the failing API wrapper test**

Create `frontend/src/api/rangeStatus.test.ts`, mirroring `frontend/src/api/ineligibleSoldiers.test.ts`'s pattern exactly (mock `./client`'s `api.get`, dynamic `await import()`):

```typescript
import { describe, expect, it, vi } from "vitest";

vi.mock("./client", () => ({ api: { get: vi.fn() } }));

describe("getSoldierRangeStatus", () => {
  it("calls the soldier-scoped range-status endpoint", async () => {
    const { api } = await import("./client");
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { soldier_id: "s1", statuses: [] },
    });
    const { getSoldierRangeStatus } = await import("./rangeStatus");

    const result = await getSoldierRangeStatus("s1");

    expect(api.get).toHaveBeenCalledWith("/soldiers/s1/range-status");
    expect(result).toEqual({ soldier_id: "s1", statuses: [] });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- api/rangeStatus` (from `frontend/`)
Expected: FAIL with module-not-found for `./rangeStatus`

- [ ] **Step 3: Implement `rangeStatus.ts`**

Create `frontend/src/api/rangeStatus.ts`:

```typescript
import type { RangeType } from "./ranges";
import { api } from "./client";

export interface RangeStatus {
  required_range_type: RangeType;
  eligible: boolean;
  qualification_source: string | null;
  covered_by_range_date: string | null;
  covering_range_type: RangeType | null;
  projected_valid_until: string | null;
  last_qualification_type: RangeType | null;
  last_qualification_date: string | null;
}

export interface SoldierRangeStatusResponse {
  soldier_id: string;
  statuses: RangeStatus[];
}

export function getSoldierRangeStatus(soldierId: string): Promise<SoldierRangeStatusResponse> {
  return api
    .get<SoldierRangeStatusResponse>(`/soldiers/${soldierId}/range-status`)
    .then((response) => response.data);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- api/rangeStatus` (from `frontend/`)
Expected: PASS

- [ ] **Step 5: Add i18n keys for the status display**

Add to `frontend/src/i18n/he.json` inside `range_qualification`, as a new sibling object next to `explanation`/`shiftDetail`:

```json
    "status": {
      "sectionTitle": "מצב מטווחים",
      "eligible": "כשיר",
      "ineligible": "לא כשיר"
    },
```

- [ ] **Step 6: Add the ProfilePage section**

In `frontend/src/pages/ProfilePage.tsx`, add imports near the top (alongside existing API/hook imports):

```typescript
import { useQuery } from "@tanstack/react-query";
import { getSoldierRangeStatus } from "../api/rangeStatus";
import { formatRangeEligibilityExplanation } from "../utils/rangeEligibilityExplanation";
```

Inside the component body (near other `useQuery` calls, before the `return`):

```typescript
  const { data: rangeStatus } = useQuery({
    queryKey: ["soldierRangeStatus", user?.id],
    queryFn: () => getSoldierRangeStatus(user!.id),
    enabled: !!user?.id,
  });
```

Insert a new block immediately after line 266 (right after the existing `last_alal_date` display, still inside the same `grid grid-cols-2 gap-4 text-sm` div):

```tsx
              {rangeStatus && rangeStatus.statuses.length > 0 && (
                <div className="col-span-2">
                  <span className="font-medium">{t("range_qualification.status.sectionTitle")}:</span>
                  <ul className="mt-1 space-y-1">
                    {rangeStatus.statuses.map((s) => (
                      <li key={s.required_range_type} className="text-xs">
                        {formatRangeEligibilityExplanation(
                          {
                            eligible: s.eligible,
                            required_range_type: s.required_range_type,
                            qualification_source: s.qualification_source,
                            covered_by_range_date: s.covered_by_range_date,
                            covering_range_type: s.covering_range_type,
                            projected_valid_until: s.projected_valid_until,
                            reason: null,
                            duty_type_name: "",
                            start_date: "",
                            last_qualification_type: s.last_qualification_type,
                            last_qualification_date: s.last_qualification_date,
                          },
                          t,
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
```

(`user` here is the existing `Me` object already in scope in `ProfilePage.tsx` from `useAuth()` — confirm the exact variable name already used in the file rather than assuming `user`.)

- [ ] **Step 7: Add the UnifiedSoldierModal "profile" tab section**

In `frontend/src/components/UnifiedSoldierModal.tsx`, add the same imports as Step 6. Inside the component, add a query keyed by the viewed soldier's id (not the logged-in user's):

```typescript
  const { data: rangeStatus } = useQuery({
    queryKey: ["soldierRangeStatus", soldierData.id],
    queryFn: () => getSoldierRangeStatus(soldierData.id),
    enabled: tab === "profile",
  });
```

Insert into the read-only "profile" tab block, right after line 382 (`last_alal_date` display) and before the `service_type` row (line 383):

```tsx
      {rangeStatus && rangeStatus.statuses.length > 0 && (
        <div>
          <span className="text-gray-500 dark:text-gray-400">{t("range_qualification.status.sectionTitle")}</span>
          <ul className="mt-1 space-y-1">
            {rangeStatus.statuses.map((s) => (
              <li key={s.required_range_type} className="text-xs">
                {formatRangeEligibilityExplanation(
                  {
                    eligible: s.eligible,
                    required_range_type: s.required_range_type,
                    qualification_source: s.qualification_source,
                    covered_by_range_date: s.covered_by_range_date,
                    covering_range_type: s.covering_range_type,
                    projected_valid_until: s.projected_valid_until,
                    reason: null,
                    duty_type_name: "",
                    start_date: "",
                    last_qualification_type: s.last_qualification_type,
                    last_qualification_date: s.last_qualification_date,
                  },
                  t,
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
```

- [ ] **Step 8: Run frontend build/typecheck to catch wiring issues**

Run: `npm run typecheck` (from `frontend/`)
Expected: PASS — fix any type errors from the inline `DutyEligibilityFact`-shaped object literals before proceeding (e.g. if `RangeType` casting is needed for `required_range_type: ""` placeholders, use `as RangeType` narrowly on just that literal, not a blanket `any`)

- [ ] **Step 9: Run the i18n completeness test**

Run: `npm test -- i18n/he.test` (from `frontend/`)
Expected: PASS

- [ ] **Step 10: Manually verify in the running app**

Start the dev stack (`.\dev.ps1` per project convention), log in as a soldier with an אל"ל-requiring duty type in scope, open `/profile`, confirm the new "מצב מטווחים" section renders; open `UnifiedSoldierModal` for another soldier as a duty manager, confirm the profile tab shows the same section.

- [ ] **Step 11: Commit**

```bash
git add frontend/src/api/rangeStatus.ts frontend/src/api/rangeStatus.test.ts frontend/src/pages/ProfilePage.tsx frontend/src/components/UnifiedSoldierModal.tsx frontend/src/i18n/he.json
git commit -m "feat: show soldier range-qualification status on profile page and modal"
```

---

## Task 6: Frontend — calendar event badges + remove top-of-page warning

**Files:**
- Modify: `frontend/src/components/UnitCalendar.tsx`
- Modify: `frontend/src/api/calendar.ts` (remove `getCalendarWeaponIneligibleCount` if confirmed unused elsewhere)
- Modify: `frontend/src/pages/UnitCalendarPage.tsx` (drop `weaponIneligibleOnly` prop wiring)
- Modify: `frontend/src/i18n/he.json`
- Test: `frontend/src/components/UnitCalendar.test.tsx`

**Interfaces:**
- Consumes: `CalendarShiftAssignee.weapon_ineligible` and `.range_eligibility` (already present in `api/calendar.ts`, unchanged); `formatRangeEligibilityExplanation` (Task 4); `useAuth()`'s `user` for role-gating.

- [ ] **Step 1: Confirm `getCalendarWeaponIneligibleCount` has no other callers before removing it**

Run: `grep -rn "getCalendarWeaponIneligibleCount" frontend/src` (or use the repo's Grep tool) — if the only remaining call site after this task's edits is `UnitCalendar.tsx`, remove the function from `calendar.ts` in Step 6 below; if other call sites exist, leave the function in place and only remove `UnitCalendar.tsx`'s usage of it.

- [ ] **Step 2: Write the failing test for the warning badge**

Add to `frontend/src/components/UnitCalendar.test.tsx`, reusing its existing `shift()` factory (extend the factory call with a `range_eligibility`-carrying assignee) and its existing `useAuth` mock (override the mocked return value per-test to a duty-manager user):

```typescript
it("shows a warning badge on the event when an assignee is weapon-ineligible, for duty managers", async () => {
  vi.mocked(useAuth).mockReturnValue({
    user: { role: "soldier", is_duty_manager: true, is_commander: false },
  } as ReturnType<typeof useAuth>);
  const testShift = shift({
    assignees: [{
      assignment_id: "a1", soldier_id: "s1", soldier_name: "Test Soldier",
      weapon_ineligible: true, weapon_ineligible_reason: "weapon_qualification",
      range_eligibility: {
        eligible: false, required_range_type: "alal", qualification_source: null,
        covered_by_range_date: null, covering_range_type: null, projected_valid_until: null,
        reason: "weapon_qualification", duty_type_name: "alal-duty", start_date: "2026-11-11",
        last_qualification_type: null, last_qualification_date: null,
      },
    }],
  });
  mockGetCalendarShifts.mockResolvedValue({ shifts: [testShift] });

  render(<UnitCalendar nodeId="node-1" />, { wrapper: makeWrapper() });
  await waitFor(() => screen.getByTestId(`shift-warning-badge-${testShift.id}`));

  expect(screen.getByTestId(`shift-warning-badge-${testShift.id}`)).toBeInTheDocument();
});

it("does not show badges for a plain soldier", async () => {
  vi.mocked(useAuth).mockReturnValue({
    user: { role: "soldier", is_duty_manager: false, is_commander: false },
  } as ReturnType<typeof useAuth>);
  const testShift = shift({
    assignees: [{
      assignment_id: "a1", soldier_id: "s1", soldier_name: "Test Soldier",
      weapon_ineligible: true, weapon_ineligible_reason: "weapon_qualification",
      range_eligibility: null,
    }],
  });
  mockGetCalendarShifts.mockResolvedValue({ shifts: [testShift] });

  render(<UnitCalendar nodeId="node-1" />, { wrapper: makeWrapper() });
  await waitFor(() => screen.getByText(testShift.duty_type_name));

  expect(screen.queryByTestId(`shift-warning-badge-${testShift.id}`)).not.toBeInTheDocument();
});
```

(Match the file's actual existing helper names for `makeWrapper`/`mockGetCalendarShifts`/the `useAuth` mock target — read the top of `UnitCalendar.test.tsx` first and adapt these calls to what's actually there rather than inventing new helper names.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `npm test -- UnitCalendar` (from `frontend/`)
Expected: FAIL — `getByTestId` finds nothing (badge doesn't exist yet)

- [ ] **Step 4: Add i18n keys for the badges**

Add to `frontend/src/i18n/he.json` inside `unit_calendar` (near the existing `weapon_ineligible_count` key at line 415), and remove the two keys that are being retired (`weapon_ineligible_filter`, `weapon_ineligible_count`) only after confirming in Step 1 that nothing else references them (`he.test.ts`'s i18n-completeness test will fail loudly if a removed key is still referenced somewhere):

```json
    "eventWarningBadge": "{{count}} חיילים לא כשירים למטווח",
    "eventInfoBadge": "צפוי לעשות {{rangeType}} ב{{date}}",
```

- [ ] **Step 5: Add the badge-rendering logic to `eventContent`**

In `frontend/src/components/UnitCalendar.tsx`, add near the top of the component (after existing hook calls like `useAuth()` — if `useAuth()` isn't already imported/called in this file, add `import { useAuth } from "../auth/AuthContext";` and `const { user } = useAuth();`):

```typescript
  const canSeeEligibilityBadges =
    user?.role === "admin" || user?.is_duty_manager || user?.is_commander;
```

Inside `eventContent`, after `const shift = shifts.find(...)` (line 339-340) and before the `swapCount` line (341), compute:

```typescript
            const ineligibleAssignees = canSeeEligibilityBadges
              ? shift.assignees.filter((a) => a.weapon_ineligible)
              : [];
            const plannedCoverageAssignee = canSeeEligibilityBadges && ineligibleAssignees.length === 0
              ? shift.assignees.find((a) => a.range_eligibility?.qualification_source === "planned_range")
              : undefined;
```

Add the badges into the JSX, in the same `flex items-center gap-1` row as `swapCount` (lines 352-358), right before the `swapCount` badge:

```tsx
                  {ineligibleAssignees.length > 0 && (
                    <span
                      data-testid={`shift-warning-badge-${shift.id}`}
                      title={
                        ineligibleAssignees.length === 1
                          ? formatRangeEligibilityExplanation(ineligibleAssignees[0].range_eligibility!, t)
                          : t("unit_calendar.eventWarningBadge", { count: ineligibleAssignees.length })
                      }
                      className="inline-flex items-center rounded bg-red-100 px-1 text-red-700 dark:bg-red-950 dark:text-red-300 flex-shrink-0"
                    >
                      ⚠
                    </span>
                  )}
                  {plannedCoverageAssignee?.range_eligibility?.covered_by_range_date && (
                    <span
                      data-testid={`shift-info-badge-${shift.id}`}
                      title={t("unit_calendar.eventInfoBadge", {
                        rangeType:
                          RANGE_TYPE_LABELS[plannedCoverageAssignee.range_eligibility.covering_range_type ?? ""]
                          ?? plannedCoverageAssignee.range_eligibility.covering_range_type,
                        date: plannedCoverageAssignee.range_eligibility.covered_by_range_date,
                      })}
                      className="inline-flex items-center rounded bg-blue-100 px-1 text-blue-700 dark:bg-blue-950 dark:text-blue-300 flex-shrink-0"
                    >
                      ℹ
                    </span>
                  )}
```

Import `formatRangeEligibilityExplanation` and `RANGE_TYPE_LABELS` at the top of the file if not already imported.

- [ ] **Step 6: Remove the top-of-page warning pill and status line**

In `frontend/src/components/UnitCalendar.tsx`, delete lines 247-255 (`weaponIneligibleOnly` status `<p>`) and lines 256-265 (`weaponIneligibleCount` pill `<span>`). Remove the now-unused `weaponIneligibleOnly` prop from `UnitCalendarProps` (lines 37-47) and its usages; remove the `weaponIneligibleCount` state/fetch logic (the `warningCountRequestRef` pattern and `getCalendarWeaponIneligibleCount` call inside `fetchData`) if Step 1 confirmed no other consumer needs it. If `getCalendarWeaponIneligibleCount` is confirmed unused anywhere else, also remove it from `frontend/src/api/calendar.ts` (lines 104-113).

- [ ] **Step 7: Update `UnitCalendarPage.tsx`**

In `frontend/src/pages/UnitCalendarPage.tsx`, remove the `weaponIneligibleOnly` variable (line 42) and its pass-through to `<UnitCalendar>` (line 69), since the prop no longer exists. Leave the `?filter=weapon_ineligible` query-param reading in place only if something else still constructs that link (per the research finding, nothing does — so remove the `useSearchParams`-derived `weaponIneligibleOnly` entirely; keep `useSearchParams` itself only if used for other params in the same file).

- [ ] **Step 8: Run tests to verify they pass**

Run: `npm test -- UnitCalendar` (from `frontend/`)
Expected: PASS

- [ ] **Step 9: Run the full frontend test suite for regressions**

Run: `npm test` (from `frontend/`)
Expected: PASS — pay particular attention to `ShiftsPage.test.tsx`, `UnitCalendar.test.tsx`, `he.test.ts`, and any test asserting the now-removed `unit-calendar-weapon-filter`/`unit-calendar-weapon-warning` `data-testid`s; update or remove those assertions

- [ ] **Step 10: Run lint and typecheck**

Run: `npm run lint` (from `frontend/`)
Run: `npm run typecheck` (from `frontend/`)
Expected: PASS (zero warnings)

- [ ] **Step 11: Manually verify in the running app**

Start the dev stack, log in as a duty manager, open the unit calendar, confirm the top-of-page warning pill/status line is gone and a warning/info badge appears on shifts with ineligible/upcoming-covered assignees; log in as a plain soldier and confirm no badges appear.

- [ ] **Step 12: Commit**

```bash
git add frontend/src/components/UnitCalendar.tsx frontend/src/api/calendar.ts frontend/src/pages/UnitCalendarPage.tsx frontend/src/i18n/he.json frontend/src/components/UnitCalendar.test.tsx
git commit -m "feat: move weapon-eligibility warning onto per-event calendar badges"
```

---

## Task 7: Frontend — homepage אל"ל gate uses `alal_relevant`

**Files:**
- Modify: `frontend/src/api/auth.ts` (`Me` interface — add `alal_relevant`)
- Modify: `frontend/src/components/dashboard/AlertBanners.tsx:92`
- Test: `frontend/src/components/dashboard/AlertBanners.test.tsx` (create if it doesn't exist, or extend if it does — check first)

**Interfaces:**
- Consumes: `alal_relevant: boolean` field added to the `/me` response in Task 3.

- [ ] **Step 1: Check for an existing `AlertBanners.test.tsx`**

Run: `ls frontend/src/components/dashboard/AlertBanners.test.tsx` (or use Glob) — if it exists, read it fully to match its existing render/mock setup before writing new tests; if not, create it following the same `render`/`QueryClientProvider`/i18n-mock conventions as `UnitCalendar.test.tsx`.

- [ ] **Step 2: Add `alal_relevant` to the `Me` interface**

In `frontend/src/api/auth.ts`, add to the `Me` interface (in the field list matching lines 9-41 reported by research — insert alongside `is_officer`/`is_career`):

```typescript
  alal_relevant?: boolean;
```

- [ ] **Step 3: Write the failing test**

Add (or create) in `frontend/src/components/dashboard/AlertBanners.test.tsx`:

```typescript
it("shows the alal banner only when alal_relevant is true, regardless of is_officer/is_career", () => {
  vi.mocked(useAuth).mockReturnValue({
    user: { is_officer: false, is_career: false, alal_relevant: true },
  } as ReturnType<typeof useAuth>);

  render(
    <AlertBanners lastMitvahimDate={null} lastAlalDate={null} settings={{}} />,
    { wrapper: makeWrapper() },
  );

  expect(screen.getByText(/אל"ל/)).toBeInTheDocument();
});

it("hides the alal banner when alal_relevant is false even for an officer", () => {
  vi.mocked(useAuth).mockReturnValue({
    user: { is_officer: true, is_career: false, alal_relevant: false },
  } as ReturnType<typeof useAuth>);

  render(
    <AlertBanners lastMitvahimDate={null} lastAlalDate={null} settings={{}} />,
    { wrapper: makeWrapper() },
  );

  expect(screen.queryByText(/אל"ל/)).not.toBeInTheDocument();
});
```

(Adapt `makeWrapper`/`useAuth` mock target to whatever convention the file/its siblings already use — this component reads `useAuth()` directly per the research findings, so mock `../../auth/AuthContext` the same way `UnitCalendar.test.tsx` does.)

- [ ] **Step 4: Run test to verify it fails**

Run: `npm test -- AlertBanners` (from `frontend/`)
Expected: FAIL (banner still shows/hides based on `is_officer`/`is_career`)

- [ ] **Step 5: Update the gate**

In `frontend/src/components/dashboard/AlertBanners.tsx`, change line 92:

```typescript
  const isAlalRelevant = user?.alal_relevant ?? false;
```

- [ ] **Step 6: Run test to verify it passes**

Run: `npm test -- AlertBanners` (from `frontend/`)
Expected: PASS

- [ ] **Step 7: Run typecheck**

Run: `npm run typecheck` (from `frontend/`)
Expected: PASS

- [ ] **Step 8: Manually verify in the running app**

Start the dev stack, log in as a soldier whose hierarchy node has no אל"ל-requiring duty type in scope (even if `is_officer`/`is_career` is true) and confirm the homepage no longer shows the אל"ל banner; log in as a soldier who is אל"ל-relevant with no `last_alal_date` and confirm the banner still shows.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/api/auth.ts frontend/src/components/dashboard/AlertBanners.tsx frontend/src/components/dashboard/AlertBanners.test.tsx
git commit -m "fix: gate homepage alal warning by structural relevance instead of officer/career flag"
```

---

## Final verification

- [ ] Run the full backend fast suite: `pytest -q` (from `backend/`, venv active) — expect PASS
- [ ] Run the full frontend suite: `npm test` (from `frontend/`) — expect PASS
- [ ] Run `npm run lint` and `npm run typecheck` (from `frontend/`) — expect zero warnings/errors
- [ ] Start `.\dev.ps1` and manually walk through: ProfilePage range-status section (self), UnifiedSoldierModal profile tab range-status (as duty manager viewing another soldier), calendar event badges (as duty manager — visible; as plain soldier — not visible), homepage אל"ל banner gated correctly
