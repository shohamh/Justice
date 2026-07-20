# Date Validation Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close two classes of missing validation: (1) self-submitted exemption/constraint requests can span an unbounded date range (the reported failure mode: a soldier submits "from today to the same date next year," approvers don't notice the year has rolled over, and it gets rubber-stamped); (2) soldier profile dates have no cross-field sanity checks (discharge before enlistment, mandatory-end after discharge, a career-track soldier with an already-past discharge date).

**Architecture:** A small shared helper (`app/services/date_validation.py`) enforces a 364-day (1 year minus 1 day) span cap, called from the three *self-submitted request* entry points (exemption requests, commander-escalated exemption requests, personal constraints) — not from direct admin/commander grants, which legitimately support open-ended ("forever") exemptions and are made by a trusted actor with full context, not a naive requester. Soldier profile cross-field checks live in `app/services/soldiers.py` as a single `validate_soldier_dates` function, called from every path that can change a soldier's dates: `update_soldier_profile`, `approve_field_update`, and `registration.register`.

**Tech Stack:** Python, SQLAlchemy (backend services layer only — no schema/migration changes).

## Global Constraints

- The 364-day span cap applies only to soldier/commander-*submitted requests* (`exemption_requests.submit_request`, `exemption_requests.submit_commander_escalation`, `constraints.submit_constraint`) — **not** to `exemptions.grant_exemption` or `exemptions.grant_commander_exemption`, which must keep supporting `end_date=None` (permanent/open-ended exemptions granted directly by a commander/admin).
- `PersonalConstraint.end_date` is already required (non-optional) and constraints already have an existing, separately-configurable `constraints.personal_cap_days` setting (default 15 days total). The new 364-day check is an additional hard ceiling independent of that setting, not a replacement for it.
- Soldier profile validation uses `Soldier.is_career: bool` (already on the model) to identify career-track soldiers — not the free-text `rank` string.
- `enlistment_date` cannot currently be changed after registration (it's not in `SOLDIER_EDITABLE_FIELDS`/`approve_field_update`'s field list, and not in `UpdateProfileRequest`) — the discharge-vs-enlistment check therefore only ever fires from `registration.register` (where both are first set) and from `update_soldier_profile` (DM/admin direct edit, which can set `discharge_date` against an existing `enlistment_date`).

---

### Task 1: Max-span cap on self-submitted exemption/constraint requests

**Files:**
- Create: `backend/app/services/date_validation.py`
- Modify: `backend/app/services/exemption_requests.py`
- Modify: `backend/app/services/constraints.py`
- Test: `backend/app/services/tests/test_exemption_requests.py`
- Test: `backend/app/services/tests/test_constraints.py` (new file — no constraints service test file exists yet; check with `ls backend/app/services/tests/ | grep constraint` first in case one was added since this plan was written)

**Interfaces:**
- Produces: `check_max_span(start_date: date, end_date: date | None, error_cls: type[Exception], message: str = "date_range_too_long") -> None` — raises `error_cls(message)` if `end_date` is set and `(end_date - start_date).days > 364`; does nothing if `end_date is None`.

- [ ] **Step 1: Write the failing tests**

Check the existing test files' fixtures first (`grep -n "^def test_\|^from\|^import" backend/app/services/tests/test_exemption_requests.py backend/app/services/tests/test_constraints.py | head -30`) and match their conventions. Append to `backend/app/services/tests/test_exemption_requests.py`:

```python
from datetime import date, timedelta


def test_submit_request_rejects_span_over_364_days(admin_session):
    from app.services.exemption_requests import submit_request, ExemptionRequestError
    from app.db.models import ExemptionType
    from tests.helpers import create_soldier

    et = ExemptionType(name="span_test_type", description=None)
    admin_session.add(et)
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number="7910001")

    start = date.today()
    with pytest.raises(ExemptionRequestError, match="date_range_too_long"):
        submit_request(
            admin_session, soldier.id, et.id,
            start_date=start, end_date=start + timedelta(days=365),
        )


def test_submit_request_allows_span_of_exactly_364_days(admin_session):
    from app.services.exemption_requests import submit_request
    from app.db.models import ExemptionType
    from tests.helpers import create_soldier

    et = ExemptionType(name="span_test_type_ok", description=None)
    admin_session.add(et)
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number="7910002")

    start = date.today()
    req = submit_request(
        admin_session, soldier.id, et.id,
        start_date=start, end_date=start + timedelta(days=364),
    )
    assert req.id is not None


def test_submit_request_allows_open_ended(admin_session):
    from app.services.exemption_requests import submit_request
    from app.db.models import ExemptionType
    from tests.helpers import create_soldier

    et = ExemptionType(name="span_test_type_open", description=None)
    admin_session.add(et)
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number="7910003")

    req = submit_request(admin_session, soldier.id, et.id, start_date=date.today(), end_date=None)
    assert req.end_date is None
```

Add `import pytest` at the top of `test_exemption_requests.py` if it isn't already imported (check first).

Create `backend/app/services/tests/test_constraints.py` (no such file exists yet — check with `ls backend/app/services/tests/ | grep constraint` first in case one was added since this plan was written, and append to it instead if so):

```python
from __future__ import annotations

from datetime import date, timedelta

import pytest

from tests.helpers import create_soldier


def test_submit_constraint_rejects_span_over_364_days(admin_session):
    from app.services.constraints import submit_constraint, ConstraintError
    from app.services.settings_loader import set_setting

    soldier = create_soldier(admin_session, personal_number="7910004")
    # Raise the personal cap so the 364-day check is what actually fires here,
    # not the pre-existing (lower, default 15-day) constraints.personal_cap_days cap.
    set_setting(admin_session, "constraints.personal_cap_days", 10000, actor_id=None)
    admin_session.commit()

    start = date.today() + timedelta(days=1)
    with pytest.raises(ConstraintError, match="date_range_too_long"):
        submit_constraint(
            admin_session, soldier_id=soldier.id,
            start_date=start, end_date=start + timedelta(days=365), reason="test",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_exemption_requests.py app/services/tests/test_constraints.py -k "span" -v`
Expected: FAIL — no span check exists yet, so the 365-day submissions succeed instead of raising.

- [ ] **Step 3: Implement the shared helper**

Create `backend/app/services/date_validation.py`:

```python
from __future__ import annotations

from datetime import date

MAX_REQUEST_SPAN_DAYS = 364  # 1 year minus 1 day


def check_max_span(
    start_date: date,
    end_date: date | None,
    error_cls: type[Exception],
    message: str = "date_range_too_long",
) -> None:
    """Raise error_cls(message) if end_date is set and the range exceeds
    MAX_REQUEST_SPAN_DAYS. Open-ended (end_date=None) ranges are never capped
    here — this guards self-submitted requests, not direct grants."""
    if end_date is not None and (end_date - start_date).days > MAX_REQUEST_SPAN_DAYS:
        raise error_cls(message)
```

- [ ] **Step 4: Wire it into `submit_request` and `submit_commander_escalation`**

In `backend/app/services/exemption_requests.py`, add the import:

```python
from app.services.date_validation import check_max_span
```

In `submit_request` (after the existing `if end_date and end_date < start_date:` check):

```python
    check_max_span(start_date, end_date, ExemptionRequestError)
```

In `submit_commander_escalation` (it currently has no date-range check at all — add right after the `if apply_immediately and commander_exemption_type_id is None:` check, before anything else uses `start_date`/`end_date`):

```python
    if end_date is not None and end_date < start_date:
        raise ExemptionRequestError("bad_date_range")
    check_max_span(start_date, end_date, ExemptionRequestError)
```

- [ ] **Step 5: Wire it into `submit_constraint`**

In `backend/app/services/constraints.py`, add the import:

```python
from app.services.date_validation import check_max_span
```

In `submit_constraint` (after the existing `if end_date < start_date:` check):

```python
    check_max_span(start_date, end_date, ConstraintError)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_exemption_requests.py app/services/tests/test_constraints.py -v`
Expected: all passed

- [ ] **Step 7: Run the full backend test suite**

Run: `cd backend && pytest -q`
Expected: no regressions.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/date_validation.py backend/app/services/exemption_requests.py backend/app/services/constraints.py backend/app/services/tests/test_exemption_requests.py backend/app/services/tests/test_constraints.py
git commit -m "feat: cap self-submitted exemption/constraint requests at 364 days"
```

---

### Task 2: Soldier profile date cross-field validation

**Files:**
- Modify: `backend/app/services/soldiers.py`
- Modify: `backend/app/services/registration.py`
- Test: `backend/app/services/tests/test_soldiers.py` (new file — no soldiers service test file exists yet; check with `ls backend/app/services/tests/ | grep test_soldiers` first in case one was added since this plan was written)
- Test: `backend/app/services/tests/test_registration.py`

**Interfaces:**
- Produces: `SoldierValidationError(SoldierError)` (new exception, in `app/services/soldiers.py`); `validate_soldier_dates(soldier: Soldier) -> None` — raises `SoldierValidationError` if the soldier's current `enlistment_date`/`discharge_date`/`mandatory_end_date`/`is_career` combination is invalid.

- [ ] **Step 1: Write the failing tests**

Create `backend/app/services/tests/test_soldiers.py`:

```python
from __future__ import annotations

from datetime import date, timedelta

import pytest


def test_update_soldier_profile_rejects_discharge_before_enlistment(admin_session):
    from app.services.soldiers import update_soldier_profile, SoldierValidationError
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920001")
    soldier.enlistment_date = date(2024, 1, 1)
    admin_session.commit()

    with pytest.raises(SoldierValidationError, match="discharge_date"):
        update_soldier_profile(
            admin_session, soldier=soldier,
            fields={"discharge_date": date(2023, 1, 1)}, actor_id=None,
        )


def test_update_soldier_profile_rejects_mandatory_end_after_discharge(admin_session):
    from app.services.soldiers import update_soldier_profile, SoldierValidationError
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920002")
    soldier.enlistment_date = date(2024, 1, 1)
    soldier.discharge_date = date(2026, 1, 1)
    admin_session.commit()

    with pytest.raises(SoldierValidationError, match="mandatory_end_date"):
        update_soldier_profile(
            admin_session, soldier=soldier,
            fields={"mandatory_end_date": date(2026, 6, 1)}, actor_id=None,
        )


def test_update_soldier_profile_rejects_career_discharge_in_past(admin_session):
    from app.services.soldiers import update_soldier_profile, SoldierValidationError
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920003")
    soldier.is_career = True
    soldier.enlistment_date = date(2020, 1, 1)
    admin_session.commit()

    with pytest.raises(SoldierValidationError, match="career"):
        update_soldier_profile(
            admin_session, soldier=soldier,
            fields={"discharge_date": date.today() - timedelta(days=1)}, actor_id=None,
        )


def test_update_soldier_profile_allows_valid_dates(admin_session):
    from app.services.soldiers import update_soldier_profile
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920004")
    soldier.enlistment_date = date(2024, 1, 1)
    admin_session.commit()

    update_soldier_profile(
        admin_session, soldier=soldier,
        fields={"discharge_date": date(2026, 1, 1), "mandatory_end_date": date(2025, 12, 1)},
        actor_id=None,
    )
    assert soldier.discharge_date == date(2026, 1, 1)


def test_approve_field_update_rejects_discharge_before_enlistment(admin_session):
    from app.services.soldiers import submit_field_update, approve_field_update, SoldierValidationError
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920005")
    soldier.enlistment_date = date(2024, 1, 1)
    admin_session.commit()

    upd = submit_field_update(
        admin_session, soldier_id=soldier.id, field_name="discharge_date",
        new_value="2023-01-01", actor_id=soldier.id,
    )
    admin_session.commit()

    with pytest.raises(SoldierValidationError, match="discharge_date"):
        approve_field_update(admin_session, update=upd, actor_id=soldier.id)
```

`backend/app/services/tests/test_registration.py` already has a `_base(**overrides)` helper (returns `personal_number`, `full_name`, `enlistment_date=date(2023,1,1)`, `discharge_date=date(2026,1,1)`, etc. — but not `is_career`, which every call passes separately) and a `_make_holding(session)` helper used to set up the holding node before registering. Append, following the same pattern as `test_register_places_soldier_in_holding_node`:

```python
def test_register_rejects_discharge_before_enlistment(admin_session):
    from app.services.registration import register, RegistrationError
    from app.services.invite_codes import create_invite_code

    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    with pytest.raises(RegistrationError, match="discharge_date"):
        register(
            admin_session, invite_code=invite.code, requested_node_id=node.id,
            exemption_requests=[], personal_constraints=[], is_career=False,
            **_base(enlistment_date=date(2024, 1, 1), discharge_date=date(2023, 1, 1)),
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_soldiers.py app/services/tests/test_registration.py -k "discharge or mandatory_end or career" -v`
Expected: FAIL — `ImportError: cannot import name 'SoldierValidationError'`.

- [ ] **Step 3: Implement the validator**

In `backend/app/services/soldiers.py`, add after `class PasswordPolicyError(SoldierError):`:

```python
class SoldierValidationError(SoldierError):
    """Raised when a soldier's date fields fail a cross-field sanity check."""


def _check_soldier_dates(
    *,
    enlistment_date: date | None,
    discharge_date: date | None,
    mandatory_end_date: date | None,
    is_career: bool,
) -> None:
    if discharge_date is not None and enlistment_date is not None and discharge_date <= enlistment_date:
        raise SoldierValidationError("discharge_date must be after enlistment_date")
    if mandatory_end_date is not None and discharge_date is not None and mandatory_end_date > discharge_date:
        raise SoldierValidationError("mandatory_end_date must not be after discharge_date")
    if is_career and discharge_date is not None and discharge_date < date.today():
        raise SoldierValidationError("career soldier's discharge_date cannot be in the past")


def validate_soldier_dates(soldier: Soldier) -> None:
    _check_soldier_dates(
        enlistment_date=soldier.enlistment_date,
        discharge_date=soldier.discharge_date,
        mandatory_end_date=soldier.mandatory_end_date,
        is_career=soldier.is_career,
    )
```

- [ ] **Step 4: Call it from `update_soldier_profile`**

In `update_soldier_profile`, right after the `for k, v in fields.items(): ...` loop and before `write_audit(...)`:

```python
    validate_soldier_dates(soldier)
```

- [ ] **Step 5: Call it from `approve_field_update`**

In `approve_field_update`, right after the `if/elif` chain that applies the field to `soldier` and before `update.status = "approved"`:

```python
    validate_soldier_dates(soldier)
```

- [ ] **Step 6: Call it from `registration.register`**

In `backend/app/services/registration.py`, add the import:

```python
from app.services.soldiers import SoldierError, _check_soldier_dates
```

Right after the existing `if session.get(HierarchyNode, requested_node_id) is None: raise RegistrationError("requested node not found")` check, before `soldier = Soldier(...)`:

```python
    try:
        _check_soldier_dates(
            enlistment_date=enlistment_date, discharge_date=discharge_date,
            mandatory_end_date=mandatory_end_date, is_career=is_career,
        )
    except SoldierError as exc:
        raise RegistrationError(str(exc)) from exc
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_soldiers.py app/services/tests/test_registration.py -v`
Expected: all passed

- [ ] **Step 8: Run the full backend test suite**

Run: `cd backend && pytest -q`
Expected: no regressions. Pay particular attention to any existing fixture/seed data (`backend/app/scripts/seed.py`) or other tests that create soldiers with `is_career=True` and a `discharge_date` in the past — if any exist and now fail, that's exactly the class of bad data this validation is meant to catch; fix the fixture's dates rather than loosening the check.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/soldiers.py backend/app/services/registration.py backend/app/services/tests/test_soldiers.py backend/app/services/tests/test_registration.py
git commit -m "feat: validate soldier profile date cross-field constraints"
```

---

### Task 3: Show span duration next to every exemption/constraint date range

**Motivation:** the reported failure mode from the Goal section (a soldier submits "today to the same date next year," and approvers don't notice the span) is a UI visibility gap as much as a backend one. `frontend/src/components/ExemptionsPanel.tsx` and `frontend/src/pages/ApprovalsPage.tsx` already each define their own local, duplicated `daysBetween`/`DaysBadge` helper and use it on *some* date ranges but not others. This task extracts that into one shared component and applies it to every remaining exemption/constraint date-range display, so an approver always sees `start → end (N days)` and never a bare range.

**Files:**
- Create: `frontend/src/components/DaysBadge.tsx`
- Modify: `frontend/src/components/ExemptionsPanel.tsx` (remove local `daysBetween`/`DaysBadge`, import shared one, add to the expired-items range at ~line 208 and the request-history range at ~line 250 — both currently missing it)
- Modify: `frontend/src/pages/ApprovalsPage.tsx` (remove local `daysBetween`/`DaysBadge`, import shared one — behavior unchanged, already applied at both call sites)
- Modify: `frontend/src/components/ExemptionInstanceModal.tsx` (add next to the start/end display at ~lines 56-58)
- Modify: `frontend/src/pages/MyRequestsPage.tsx` (add to all constraint ranges at ~lines 181, 200, 217, and both exemption/exemption-request ranges at ~lines 370, 406 — none currently have it)
- Test: `frontend/src/components/ExemptionsPanel.test.tsx`
- Test: `frontend/src/pages/MyRequestsPage.test.tsx` (check with `ls frontend/src/pages/ | grep MyRequestsPage.test` first — create if it doesn't exist yet, following the fixture conventions of `ApprovalsPage.test.tsx`)

**Interfaces:**
- Produces: `daysBetween(start: string, end: string | null | undefined): number | null` and `DaysBadge({ start, end }: { start: string; end: string | null | undefined })` in `frontend/src/components/DaysBadge.tsx` — identical logic to the existing duplicated versions (inclusive day count: `Math.round((b - a) / 86400000) + 1`; color thresholds `> 90` red, `> 30` yellow, else gray; renders `null` when `end` is null/undefined, i.e. open-ended ranges show no badge).

- [ ] **Step 1: Extract the shared component**

Create `frontend/src/components/DaysBadge.tsx` by moving the existing `daysBetween`/`DaysBadge` definitions verbatim out of `ExemptionsPanel.tsx` (lines 15-32), as a named export:

```tsx
export function daysBetween(start: string, end: string | null | undefined): number | null {
  if (!end) return null;
  const a = new Date(start);
  const b = new Date(end);
  return Math.round((b.getTime() - a.getTime()) / (1000 * 60 * 60 * 24)) + 1;
}

export function DaysBadge({ start, end }: { start: string; end: string | null | undefined }) {
  const days = daysBetween(start, end);
  if (days === null) return null;
  const cls =
    days > 90
      ? "text-red-600 dark:text-red-400"
      : days > 30
      ? "text-yellow-600 dark:text-yellow-400"
      : "text-gray-400 dark:text-gray-500";
  return <span className={`text-xs ${cls}`}>({days} ימים)</span>;
}
```

- [ ] **Step 2: Wire the shared component into `ExemptionsPanel.tsx`**

Remove the local `daysBetween`/`DaysBadge` definitions (lines 15-32) and add `import { DaysBadge } from "./DaysBadge";`.

Add `<DaysBadge start={ex.start_date} end={ex.end_date} />` next to the expired-items range (~line 208, currently `{formatDate(ex.start_date)} → {ex.end_date ? formatDate(ex.end_date) : ""}`) and next to the request-history range (~line 250, currently `{formatDate(req.start_date)} → {req.end_date ? formatDate(req.end_date) : t("exemptions.forever")}`) — matching the pattern already used for the active-items list at line 160.

- [ ] **Step 3: Wire the shared component into `ApprovalsPage.tsx`**

Remove the local `daysBetween`/`DaysBadge` definitions and add `import { DaysBadge } from "../components/DaysBadge";`. The two existing call sites (constraints tab ~line 317, exemptions tab ~line 367) are unchanged.

- [ ] **Step 4: Add to `ExemptionInstanceModal.tsx`**

Add `import { DaysBadge } from "./DaysBadge";` and place `<DaysBadge start={detail.start_date} end={detail.end_date} />` next to the existing start/end display (~lines 56-58).

- [ ] **Step 5: Add to `MyRequestsPage.tsx`**

Add `import { DaysBadge } from "../components/DaysBadge";`. Add `<DaysBadge start={c.start_date} end={c.end_date} />` next to each of the three constraint-list ranges (~lines 181, 200, 217), `<DaysBadge start={er.start_date} end={er.end_date} />` next to the exemption-request range (~line 370), and `<DaysBadge start={ex.start_date} end={ex.end_date} />` next to the exemptions range (~line 406).

- [ ] **Step 6: Write/update tests**

In `ExemptionsPanel.test.tsx`, add a case asserting the days badge text (e.g. `"(365 ימים)"` or the appropriate count for a fixture date range) renders in both the expired-items list and the request-history list, not just the active-items list.

In `MyRequestsPage.test.tsx` (create if missing, following `ApprovalsPage.test.tsx`'s fixture/render conventions), add a case asserting a days-count badge renders next to a constraint row and an exemption-request row.

- [ ] **Step 7: Run frontend checks**

Run: `cd frontend && npm test -- --run` and `npm run typecheck`
Expected: all pass, no regressions.

- [ ] **Step 8: Manual verification**

Start the dev stack (`.\dev.ps1`), open a soldier's profile exemptions panel and the approvals page, and confirm every date range — active, expired, pending request, and both approvals tabs — now shows `start → end (N days)` (or no badge for open-ended `forever` ranges).

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/DaysBadge.tsx frontend/src/components/ExemptionsPanel.tsx frontend/src/pages/ApprovalsPage.tsx frontend/src/components/ExemptionInstanceModal.tsx frontend/src/pages/MyRequestsPage.tsx frontend/src/components/ExemptionsPanel.test.tsx frontend/src/pages/MyRequestsPage.test.tsx
git commit -m "feat: show span duration next to every exemption/constraint date range"
```
