# Swap Eligibility & Availability Enforcement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hard-block ineligible or unavailable soldiers from accepting/being targeted for swaps, and grey out confirm buttons in the UI with explanations before the user can submit.

**Architecture:** A new `check_soldier_for_assignment(session, soldier_id, assignment_id)` service helper in `services/eligibility.py` runs four checks in order (duty-type eligibility → exemptions → approved personal constraints → scheduling conflict) and returns `(eligible: bool, reason: str | None)`. All four swap write operations call this helper and raise `SwapError` on failure. A new `GET /swaps/{assignment_id}/cover-eligibility` endpoint exposes the check to the frontend. The existing `routes/swaps_eligibility.py` is refactored to use the same helper.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL 16, React 18 + TypeScript, i18next

---

## File Map

| File | Change |
|---|---|
| `backend/app/services/eligibility.py` | Add `check_soldier_for_assignment()` |
| `backend/app/routes/swaps_eligibility.py` | Refactor to call new helper |
| `backend/app/services/swaps.py` | Add guard calls in 4 write operations |
| `backend/app/routes/swaps.py` | Add `GET /swaps/{id}/cover-eligibility` endpoint |
| `backend/tests/unit/test_swap_eligibility.py` | New: unit tests for the helper |
| `backend/tests/unit/test_swaps.py` | Add: tests for enforcement in write ops |
| `frontend/src/api/swaps.ts` | Add `checkCoverEligibility()` |
| `frontend/src/components/CoverOfferModal.tsx` | Add pre-flight eligibility check |
| `frontend/src/components/OfferSwapModal.tsx` | Add pre-flight check for take-free mode |

---

## Task 1: `check_soldier_for_assignment` helper

**Files:**
- Modify: `backend/app/services/eligibility.py`
- Create: `backend/tests/unit/test_swap_eligibility.py`

- [ ] **Step 1: Create the test file with four failing cases**

Create `backend/tests/unit/test_swap_eligibility.py`:

```python
from datetime import date, timedelta

from app.db.models import (
    DutyAssignment, DutyLocation, DutyType, ExemptionDutyTypeMap,
    ExemptionType, PersonalConstraint, Soldier, SoldierExemption,
)
from app.services.eligibility import check_soldier_for_assignment


def _base(session):
    """Return (soldier, duty_type, duty_location, assignment) with no restrictions."""
    dt = DutyType(name="שמירה-elig", score_per_day=1)
    loc = DutyLocation(name="עמדה-elig")
    s = Soldier(
        personal_number="elig1", full_name="Test", password_hash="x",
        role="soldier", enrolled_at=date(2026, 1, 1), must_change_password=False,
    )
    session.add_all([dt, loc, s])
    session.flush()
    a = DutyAssignment(
        soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 7, 10), end_date=date(2026, 7, 10), status="published",
    )
    session.add(a)
    session.flush()
    return s, dt, loc, a


def test_eligible_when_no_restrictions(admin_session):
    s, dt, loc, a = _base(admin_session)
    ok, reason = check_soldier_for_assignment(admin_session, s.id, a.id)
    assert ok is True
    assert reason is None


def test_blocked_by_duty_type_eligibility(admin_session):
    s, dt, loc, a = _base(admin_session)
    # Require mitvahim but soldier has none
    dt.requirements = {"requires_mitvahim": True}
    admin_session.flush()
    ok, reason = check_soldier_for_assignment(admin_session, s.id, a.id)
    assert ok is False
    assert reason is not None


def test_blocked_by_global_exemption(admin_session):
    s, dt, loc, a = _base(admin_session)
    et = ExemptionType(name="פטור גלובלי", is_global=True)
    admin_session.add(et)
    admin_session.flush()
    ex = SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id,
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 31),
    )
    admin_session.add(ex)
    admin_session.flush()
    ok, reason = check_soldier_for_assignment(admin_session, s.id, a.id)
    assert ok is False
    assert reason == "פטור מסוג תורנות זו"


def test_blocked_by_duty_type_exemption(admin_session):
    s, dt, loc, a = _base(admin_session)
    et = ExemptionType(name="פטור שמירה", is_global=False)
    admin_session.add(et)
    admin_session.flush()
    admin_session.add(ExemptionDutyTypeMap(exemption_type_id=et.id, duty_type_id=dt.id))
    ex = SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id,
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 31),
    )
    admin_session.add(ex)
    admin_session.flush()
    ok, reason = check_soldier_for_assignment(admin_session, s.id, a.id)
    assert ok is False
    assert reason == "פטור מסוג תורנות זו"


def test_not_blocked_by_expired_exemption(admin_session):
    s, dt, loc, a = _base(admin_session)
    et = ExemptionType(name="פטור ישן", is_global=True)
    admin_session.add(et)
    admin_session.flush()
    # Exemption ended before the duty
    ex = SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 7, 9),
    )
    admin_session.add(ex)
    admin_session.flush()
    ok, reason = check_soldier_for_assignment(admin_session, s.id, a.id)
    assert ok is True


def test_blocked_by_approved_constraint(admin_session):
    s, dt, loc, a = _base(admin_session)
    c = PersonalConstraint(
        soldier_id=s.id, start_date=date(2026, 7, 8), end_date=date(2026, 7, 12),
        reason="חופש", status="approved",
    )
    admin_session.add(c)
    admin_session.flush()
    ok, reason = check_soldier_for_assignment(admin_session, s.id, a.id)
    assert ok is False
    assert reason == "אילוץ אישי מאושר בתאריך זה"


def test_not_blocked_by_pending_constraint(admin_session):
    s, dt, loc, a = _base(admin_session)
    c = PersonalConstraint(
        soldier_id=s.id, start_date=date(2026, 7, 8), end_date=date(2026, 7, 12),
        reason="חופש", status="pending",
    )
    admin_session.add(c)
    admin_session.flush()
    ok, reason = check_soldier_for_assignment(admin_session, s.id, a.id)
    assert ok is True


def test_blocked_by_scheduling_conflict(admin_session):
    s, dt, loc, a = _base(admin_session)
    # Give soldier a second published assignment that overlaps
    conflict = DutyAssignment(
        soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 7, 9), end_date=date(2026, 7, 11), status="published",
    )
    admin_session.add(conflict)
    admin_session.flush()
    ok, reason = check_soldier_for_assignment(admin_session, s.id, a.id)
    assert ok is False
    assert reason == "שיבוץ קיים בתאריכים אלו"


def test_not_blocked_by_non_published_assignment(admin_session):
    s, dt, loc, a = _base(admin_session)
    draft = DutyAssignment(
        soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 7, 9), end_date=date(2026, 7, 11), status="algorithm_draft",
    )
    admin_session.add(draft)
    admin_session.flush()
    ok, reason = check_soldier_for_assignment(admin_session, s.id, a.id)
    assert ok is True


def test_exclude_assignment_id_skips_self_conflict(admin_session):
    s, dt, loc, a = _base(admin_session)
    # The assignment being checked is itself — should not count as a conflict
    ok, reason = check_soldier_for_assignment(admin_session, s.id, a.id, exclude_assignment_id=a.id)
    assert ok is True
```

- [ ] **Step 2: Run the tests to confirm they all fail**

```powershell
cd backend; uv run pytest tests/unit/test_swap_eligibility.py -v 2>&1 | head -30
```

Expected: ImportError or NameError — `check_soldier_for_assignment` does not exist yet.

- [ ] **Step 3: Implement `check_soldier_for_assignment` in `services/eligibility.py`**

Add to the top of `backend/app/services/eligibility.py` — expand the existing imports:

```python
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment, DutyType, ExemptionDutyTypeMap, ExemptionType,
    PersonalConstraint, Soldier, SoldierExemption,
)
from app.services.settings_loader import SettingNotFound, get_setting
```

(Replace the existing `from sqlalchemy import select` and `from app.db.models import DutyType, Soldier` lines.)

Then append this function at the end of the file:

```python
def check_soldier_for_assignment(
    session: Session,
    soldier_id: uuid.UUID,
    assignment_id: uuid.UUID,
    *,
    exclude_assignment_id: uuid.UUID | None = None,
) -> tuple[bool, str | None]:
    """Return (True, None) if the soldier is eligible and available for the assignment,
    or (False, Hebrew reason) on the first failing check."""
    assignment = session.get(DutyAssignment, assignment_id)
    if assignment is None:
        return False, "שיבוץ לא נמצא"

    soldier = session.get(Soldier, soldier_id)
    if soldier is None:
        return False, "חייל לא נמצא"

    today = date.today()

    def _setting_int(key: str, default: int) -> int:
        try:
            return int(get_setting(session, key))
        except (SettingNotFound, ValueError):
            return default

    # 1. Duty type eligibility (mitvahim/alal, gender, rank, service type, bahad1, officers/enlisted)
    dt = session.get(DutyType, assignment.duty_type_id)
    if dt is not None:
        raw_reqs = dt.requirements or {}
        if raw_reqs:
            try:
                reqs = DutyTypeRequirements.model_validate(raw_reqs)
                mitvahim_months = _setting_int("eligibility.mitvahim_months", 6)
                alal_months = _setting_int("eligibility.alal_months", 3)
                if not _is_eligible(soldier, reqs, mitvahim_months=mitvahim_months,
                                    alal_months=alal_months, today=today):
                    return False, 'אי-כשירות לסוג תורנות זה'
            except Exception:
                pass

    # 2. Active exemptions overlapping the duty date range
    exemptions = session.execute(
        select(SoldierExemption).where(
            SoldierExemption.soldier_id == soldier_id,
            SoldierExemption.start_date <= assignment.end_date,
            or_(
                SoldierExemption.end_date.is_(None),
                SoldierExemption.end_date >= assignment.start_date,
            ),
        )
    ).scalars().all()

    for ex in exemptions:
        et = session.get(ExemptionType, ex.exemption_type_id)
        if et and et.is_global:
            return False, "פטור מסוג תורנות זו"
        dtype_ids = session.execute(
            select(ExemptionDutyTypeMap.duty_type_id).where(
                ExemptionDutyTypeMap.exemption_type_id == ex.exemption_type_id
            )
        ).scalars().all()
        if assignment.duty_type_id in dtype_ids:
            return False, "פטור מסוג תורנות זו"

    # 3. Approved personal constraint overlapping the duty date range
    conflict_constraint = session.execute(
        select(PersonalConstraint).where(
            PersonalConstraint.soldier_id == soldier_id,
            PersonalConstraint.status == "approved",
            PersonalConstraint.start_date <= assignment.end_date,
            PersonalConstraint.end_date >= assignment.start_date,
        )
    ).scalar_one_or_none()
    if conflict_constraint is not None:
        return False, "אילוץ אישי מאושר בתאריך זה"

    # 4. Scheduling conflict — existing published assignment for this soldier on these dates
    conflict_q = (
        select(DutyAssignment).where(
            DutyAssignment.soldier_id == soldier_id,
            DutyAssignment.status == "published",
            DutyAssignment.start_date <= assignment.end_date,
            DutyAssignment.end_date >= assignment.start_date,
        )
    )
    if exclude_assignment_id is not None:
        conflict_q = conflict_q.where(DutyAssignment.id != exclude_assignment_id)
    if session.execute(conflict_q).scalar_one_or_none() is not None:
        return False, "שיבוץ קיים בתאריכים אלו"

    return True, None
```

- [ ] **Step 4: Run the tests — all should pass**

```powershell
cd backend; uv run pytest tests/unit/test_swap_eligibility.py -v
```

Expected: 9 tests pass.

- [ ] **Step 5: Commit**

```powershell
cd backend; git add app/services/eligibility.py tests/unit/test_swap_eligibility.py
git commit -m "feat: add check_soldier_for_assignment to services/eligibility"
```

---

## Task 2: Refactor `routes/swaps_eligibility.py` to use the helper

**Files:**
- Modify: `backend/app/routes/swaps_eligibility.py`

- [ ] **Step 1: Replace the inline logic with calls to `check_soldier_for_assignment`**

Replace the entire content of `backend/app/routes/swaps_eligibility.py` with:

```python
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.auth.deps import require_password_changed
from app.db.models import DutyAssignment, Soldier
from app.db.session import get_session
from app.services.eligibility import check_soldier_for_assignment

router = APIRouter(prefix="/swaps", tags=["swaps"])


class EligibilityResult(BaseModel):
    assignment_id: uuid.UUID
    eligible: bool
    reason: str | None


@router.get("/eligible-duties", response_model=list[EligibilityResult])
def eligible_duties(
    target_soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_password_changed),
):
    """
    For each of the current user's published/active assignments, check whether
    target_soldier_id would be eligible to accept a swap for it.
    """
    today = date.today()
    my_assignments = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.soldier_id == actor.id,
            DutyAssignment.status == "published",
            DutyAssignment.end_date >= today,
        )
    ).scalars().all()

    if session.get(Soldier, target_soldier_id) is None:
        return []

    return [
        EligibilityResult(
            assignment_id=a.id,
            eligible=eligible,
            reason=reason,
        )
        for a in my_assignments
        for eligible, reason in [check_soldier_for_assignment(session, target_soldier_id, a.id)]
    ]
```

- [ ] **Step 2: Run the full test suite to check for regressions**

```powershell
cd backend; uv run pytest -q
```

Expected: all existing tests pass, no new failures.

- [ ] **Step 3: Commit**

```powershell
git add backend/app/routes/swaps_eligibility.py
git commit -m "refactor: swaps_eligibility route uses check_soldier_for_assignment helper"
```

---

## Task 3: Backend enforcement — `claim_request`, `cover_offer`, `take_free`

**Files:**
- Modify: `backend/app/services/swaps.py`
- Modify: `backend/tests/unit/test_swaps.py`

- [ ] **Step 1: Add failing tests to `backend/tests/unit/test_swaps.py`**

First, expand the existing `from app.db.models import ...` line at the top of `test_swaps.py` to include `PersonalConstraint`:

```python
from app.db.models import (
    DutyAssignment, DutyDayOverride, DutyLocation, DutyType,
    PersonalConstraint, Soldier, SwapRequest, SystemSetting,
)
```

Then append the following helper and tests at the bottom of the file:

```python
def _approved_constraint(session, soldier_id, start, end):
    c = PersonalConstraint(
        soldier_id=soldier_id, start_date=start, end_date=end,
        reason="busy", status="approved",
    )
    session.add(c)
    session.flush()
    return c


def test_claim_blocked_when_covering_has_constraint(admin_session):
    a, b, assignment = _seed(admin_session)
    set_setting(admin_session, "swaps.require_manager_approval", False, actor_id=None)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="x", actor_id=a.id,
    )
    admin_session.flush()
    _approved_constraint(admin_session, b.id, assignment.start_date, assignment.end_date)
    try:
        svc.claim_request(admin_session, request_id=req.id, covering_soldier_id=b.id, actor_id=b.id)
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc).startswith("cover_not_eligible:")


def test_claim_blocked_when_covering_has_conflict_assignment(admin_session):
    a, b, assignment = _seed(admin_session)
    set_setting(admin_session, "swaps.require_manager_approval", False, actor_id=None)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="x", actor_id=a.id,
    )
    admin_session.flush()
    # Give soldier b an existing published duty on the same dates
    conflict = DutyAssignment(
        soldier_id=b.id,
        duty_type_id=assignment.duty_type_id,
        duty_location_id=assignment.duty_location_id,
        start_date=assignment.start_date,
        end_date=assignment.end_date,
        status="published",
    )
    admin_session.add(conflict)
    admin_session.flush()
    try:
        svc.claim_request(admin_session, request_id=req.id, covering_soldier_id=b.id, actor_id=b.id)
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc).startswith("cover_not_eligible:")


def test_cover_offer_blocked_when_covering_has_constraint(admin_session):
    a, b, assignment = _seed(admin_session)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="x", actor_id=a.id,
    )
    admin_session.flush()
    _approved_constraint(admin_session, b.id, assignment.start_date, assignment.end_date)
    try:
        svc.cover_offer(admin_session, swap_id=req.id, covering_soldier_id=b.id,
                        offered_assignment_ids=[], actor_id=b.id)
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc).startswith("cover_not_eligible:")


def test_take_free_blocked_when_covering_has_constraint(admin_session):
    a, b, assignment = _seed(admin_session)
    _approved_constraint(admin_session, b.id, assignment.start_date, assignment.end_date)
    try:
        svc.take_free(admin_session, assignment_id=assignment.id,
                      covering_soldier_id=b.id, actor_id=b.id)
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc).startswith("cover_not_eligible:")
```

- [ ] **Step 2: Run the new tests to confirm they fail**

```powershell
cd backend; uv run pytest tests/unit/test_swaps.py::test_claim_blocked_when_covering_has_constraint tests/unit/test_swaps.py::test_cover_offer_blocked_when_covering_has_constraint tests/unit/test_swaps.py::test_take_free_blocked_when_covering_has_constraint -v
```

Expected: FAIL — swap operations succeed despite the constraint.

- [ ] **Step 3: Add the import and guard calls to `backend/app/services/swaps.py`**

Add this import at the top of `backend/app/services/swaps.py` (after the existing imports):

```python
from app.services.eligibility import check_soldier_for_assignment
```

In `claim_request`, add this block right after the `if session.get(Soldier, covering_soldier_id) is None:` check (around line 168):

```python
    eligible, reason = check_soldier_for_assignment(
        session, covering_soldier_id, req.duty_assignment_id
    )
    if not eligible:
        raise SwapError(f"cover_not_eligible:{reason}")
```

In `cover_offer`, add this block right after the `if req.requesting_soldier_id == covering_soldier_id:` check (around line 390):

```python
    eligible, reason = check_soldier_for_assignment(
        session, covering_soldier_id, req.duty_assignment_id
    )
    if not eligible:
        raise SwapError(f"cover_not_eligible:{reason}")
```

In `take_free`, add this block right before the `req = SwapRequest(...)` construction (around line 339), after the reserve cap check:

```python
    eligible, reason = check_soldier_for_assignment(
        session, covering_soldier_id, assignment_id
    )
    if not eligible:
        raise SwapError(f"cover_not_eligible:{reason}")
```

- [ ] **Step 4: Run the new tests — all should pass**

```powershell
cd backend; uv run pytest tests/unit/test_swaps.py -v
```

Expected: all tests including the new ones pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/swaps.py backend/tests/unit/test_swaps.py
git commit -m "feat: block ineligible covering soldiers in claim/cover_offer/take_free"
```

---

## Task 4: Backend enforcement — `create_request` with `target_soldier_id`

**Files:**
- Modify: `backend/app/services/swaps.py`
- Modify: `backend/tests/unit/test_swaps.py`

- [ ] **Step 1: Add a failing test**

Append to `backend/tests/unit/test_swaps.py`:

```python
def test_create_direct_request_blocked_when_target_has_constraint(admin_session):
    a, b, assignment = _seed(admin_session)
    _approved_constraint(admin_session, b.id, assignment.start_date, assignment.end_date)
    try:
        svc.create_request(
            admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
            target_soldier_id=b.id, reason="cover me", actor_id=a.id,
        )
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc).startswith("cover_not_eligible:")
```

- [ ] **Step 2: Run the test to confirm it fails**

```powershell
cd backend; uv run pytest tests/unit/test_swaps.py::test_create_direct_request_blocked_when_target_has_constraint -v
```

Expected: FAIL.

- [ ] **Step 3: Add guard in `create_request` in `backend/app/services/swaps.py`**

In `create_request`, add this block right after the `if target_soldier_id is not None and target_soldier_id == requesting_soldier_id:` check (around line 37):

```python
    if target_soldier_id is not None:
        eligible, reason = check_soldier_for_assignment(
            session, target_soldier_id, duty_assignment_id
        )
        if not eligible:
            raise SwapError(f"cover_not_eligible:{reason}")
```

- [ ] **Step 4: Run all swap tests**

```powershell
cd backend; uv run pytest tests/unit/test_swaps.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/swaps.py backend/tests/unit/test_swaps.py
git commit -m "feat: block targeted swap offers when target is ineligible/unavailable"
```

---

## Task 5: New `GET /swaps/{assignment_id}/cover-eligibility` endpoint

**Files:**
- Modify: `backend/app/routes/swaps.py`

- [ ] **Step 1: Add the response model and route handler to `backend/app/routes/swaps.py`**

Add the `CoverEligibilityOut` model and the new endpoint. Place the model near the other response models at the top, and the route near `swap_config`:

```python
class CoverEligibilityOut(BaseModel):
    eligible: bool
    reason: str | None
```

```python
@router.get("/swaps/{assignment_id}/cover-eligibility", response_model=CoverEligibilityOut)
def cover_eligibility(
    assignment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> CoverEligibilityOut:
    from app.services.eligibility import check_soldier_for_assignment
    assignment = session.get(DutyAssignment, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    eligible, reason = check_soldier_for_assignment(session, user.id, assignment_id)
    return CoverEligibilityOut(eligible=eligible, reason=reason)
```

- [ ] **Step 2: Run the full backend test suite**

```powershell
cd backend; uv run pytest -q
```

Expected: all pass.

- [ ] **Step 3: Commit**

```powershell
git add backend/app/routes/swaps.py
git commit -m "feat: add GET /swaps/{id}/cover-eligibility pre-flight endpoint"
```

---

## Task 6: Frontend API + `CoverOfferModal` pre-flight check

**Files:**
- Modify: `frontend/src/api/swaps.ts`
- Modify: `frontend/src/components/CoverOfferModal.tsx`

- [ ] **Step 1: Add `checkCoverEligibility` to `frontend/src/api/swaps.ts`**

Append at the end of the file:

```typescript
export interface CoverEligibilityResult {
  eligible: boolean;
  reason: string | null;
}

export async function checkCoverEligibility(
  assignmentId: string,
): Promise<CoverEligibilityResult> {
  const res = await api.get<CoverEligibilityResult>(
    `/swaps/${assignmentId}/cover-eligibility`,
  );
  return res.data;
}
```

- [ ] **Step 2: Update `frontend/src/components/CoverOfferModal.tsx`**

Replace the entire file content with:

```typescript
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { SwapRequest, submitCoverOffer, checkCoverEligibility, CoverEligibilityResult } from "../api/swaps";
import { EffectiveDuty } from "../api/assignments";

interface Props {
  swap: SwapRequest;
  myDuties: EffectiveDuty[];
  dutyTypes: Record<string, string>;
  onClose: () => void;
  onDone: () => void;
}

export default function CoverOfferModal({ swap, myDuties, dutyTypes, onClose, onDone }: Props) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<"free" | "trade">("free");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [coverCheck, setCoverCheck] = useState<CoverEligibilityResult | null>(null);
  const [coverCheckLoading, setCoverCheckLoading] = useState(true);

  useEffect(() => {
    setCoverCheckLoading(true);
    checkCoverEligibility(swap.duty_assignment_id)
      .then(setCoverCheck)
      .catch(() => setCoverCheck({ eligible: true, reason: null }))
      .finally(() => setCoverCheckLoading(false));
  }, [swap.duty_assignment_id]);

  function toggleDuty(id: string) {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  async function handleSubmit() {
    setError(null);
    try {
      await submitCoverOffer(swap.id, mode === "trade" ? selectedIds : []);
      onDone();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      if (detail?.startsWith("cover_not_eligible:")) {
        setError(detail.slice("cover_not_eligible:".length));
      } else {
        setError(detail ?? "שגיאה");
      }
    }
  }

  const ineligibleReason = !coverCheckLoading && coverCheck && !coverCheck.eligible
    ? coverCheck.reason
    : null;
  const canSubmit = !coverCheckLoading && !ineligibleReason &&
    (mode === "free" || selectedIds.length > 0);

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4 max-h-[80vh] overflow-y-auto"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold dark:text-gray-100">{t("swaps.cover")}</h3>
          <button onClick={onClose} className="text-gray-500">✕</button>
        </div>
        <div className="space-y-3">
          <label className="flex items-center gap-2 text-sm cursor-pointer dark:text-gray-300">
            <input type="radio" name="cover_mode" checked={mode === "free"} onChange={() => setMode("free")} />
            {t("swaps.cover_free")}
          </label>
          <label className="flex items-center gap-2 text-sm cursor-pointer dark:text-gray-300">
            <input type="radio" name="cover_mode" checked={mode === "trade"} onChange={() => setMode("trade")} />
            {t("swaps.offer_trade")}
          </label>
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
          {ineligibleReason && (
            <p className="text-xs text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/30 border border-amber-300 dark:border-amber-700 rounded p-2">
              {ineligibleReason}
            </p>
          )}
          {error && <p className="text-red-500 text-xs">{error}</p>}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1 text-sm border rounded dark:border-gray-600 dark:text-gray-300"
            >
              {t("swaps.cancel")}
            </button>
            <button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={!canSubmit}
              className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
              title={ineligibleReason ?? undefined}
            >
              {coverCheckLoading ? "…" : t("swaps.submit_offer")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Run the frontend linter**

```powershell
cd frontend; pnpm lint
```

Expected: zero warnings.

- [ ] **Step 4: Commit**

```powershell
git add frontend/src/api/swaps.ts frontend/src/components/CoverOfferModal.tsx
git commit -m "feat: pre-flight eligibility check in CoverOfferModal, grey out if ineligible"
```

---

## Task 7: `OfferSwapModal` take-free eligibility check

**Files:**
- Modify: `frontend/src/components/OfferSwapModal.tsx`

- [ ] **Step 1: Import `checkCoverEligibility` and add state**

In `frontend/src/components/OfferSwapModal.tsx`, update the import line for the swaps API:

```typescript
import { createSwap, takeDutyFree, listMySwaps, SwapRequest, EligibilityResult, getEligibleDuties, checkCoverEligibility, CoverEligibilityResult } from "../api/swaps";
```

Add two new state variables after the existing `eligibilityLoading` state:

```typescript
const [freeCoverCheck, setFreeCoverCheck] = useState<CoverEligibilityResult | null>(null);
const [freeCoverCheckLoading, setFreeCoverCheckLoading] = useState(true);
```

- [ ] **Step 2: Add a `useEffect` to call the pre-flight check for take-free mode**

Add this effect after the existing `eligibilityLoading` effect (around line 96):

```typescript
useEffect(() => {
  setFreeCoverCheckLoading(true);
  checkCoverEligibility(targetAssignmentId)
    .then(setFreeCoverCheck)
    .catch(() => setFreeCoverCheck({ eligible: true, reason: null }))
    .finally(() => setFreeCoverCheckLoading(false));
}, [targetAssignmentId]);
```

- [ ] **Step 3: Update `freeBlocked` and the take-free radio + reason display**

Replace the existing `freeBlocked` line:

```typescript
// Before:
const freeBlocked = conflictingDuties.length > 0;
```

With:

```typescript
const freeConflict = conflictingDuties.length > 0;
const freeIneligibleReason =
  !freeCoverCheckLoading && freeCoverCheck && !freeCoverCheck.eligible
    ? freeCoverCheck.reason
    : null;
const freeBlocked = freeConflict || !!freeIneligibleReason;
```

Replace the `freeBlocked && mode !== "free"` message block (around line 225):

```typescript
{/* Before: */}
{freeBlocked && mode !== "free" && (
  <p className="text-xs text-amber-600 dark:text-amber-400 pr-4">
    {t("swaps.free_blocked_conflict")}
  </p>
)}
```

With:

```typescript
{freeConflict && mode !== "free" && (
  <p className="text-xs text-amber-600 dark:text-amber-400 pr-4">
    {t("swaps.free_blocked_conflict")}
  </p>
)}
{freeIneligibleReason && mode !== "free" && (
  <p className="text-xs text-amber-600 dark:text-amber-400 pr-4">
    {freeIneligibleReason}
  </p>
)}
```

- [ ] **Step 4: Update `canSubmit` to account for take-free loading state**

Replace the existing `canSubmit` line:

```typescript
// Before:
const canSubmit = mode === "free" ? !freeBlocked : !!selectedDuty;
```

With:

```typescript
const canSubmit = mode === "free"
  ? !freeBlocked && !freeCoverCheckLoading
  : !!selectedDuty;
```

- [ ] **Step 5: Run the frontend linter**

```powershell
cd frontend; pnpm lint
```

Expected: zero warnings.

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/components/OfferSwapModal.tsx
git commit -m "feat: pre-flight eligibility check for take-free mode in OfferSwapModal"
```

---

## Task 8: Final verification

- [ ] **Step 1: Run the full backend test suite**

```powershell
cd backend; uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run the frontend linter and tests**

```powershell
cd frontend; pnpm lint && pnpm test
```

Expected: zero lint warnings, all tests pass.

- [ ] **Step 3: Start the dev stack and smoke-test the UI**

```powershell
.\dev.ps1 -NoBot
```

Open http://localhost:5173 and verify:
- In `CoverOfferModal`: the submit button shows `…` briefly on open, then is greyed out with amber text if ineligible, or enabled if eligible.
- In `OfferSwapModal` take-free mode: the radio is disabled with amber text if the current user is ineligible/unavailable for the target assignment.
- Attempting to bypass via direct API call (e.g., `POST /swaps/{id}/claim`) returns `400 cover_not_eligible:{reason}`.
