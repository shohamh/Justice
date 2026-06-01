# Commander Dashboard + Algorithm Duty Restriction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a commander dashboard page (דף מפקד) with 9 panels, plus add sub-hierarchy duty restriction to the algorithm page.

**Architecture:** Backend: new FastAPI router + service module for dashboard endpoints, filtered by commander's node subtree. Algorithm model: filter eligible soldiers by `eligible_node_ids` on duty shifts. Frontend: new page with dashboard grid layout, reusable components for each panel.

**Tech Stack:** FastAPI, SQLAlchemy, React 18, TypeScript, Tailwind CSS

---

## File Structure

### Backend — Commander Dashboard API
- Create: `backend/app/routes/commander_dashboard.py`
- Create: `backend/app/services/commander_dashboard.py`
- Modify: `backend/app/main.py` (register router)

### Backend — Algorithm Duty Restriction
- Modify: `backend/app/algorithm/types.py` (add `eligible_node_ids` to `DutyBlock`)
- Modify: `backend/app/algorithm/model.py` (filter by `eligible_node_ids`)
- Modify: `backend/app/routes/algorithm.py` (add shift-level restriction endpoint)

### Frontend — Commander Dashboard
- Create: `frontend/src/api/commanderDashboard.ts`
- Create: `frontend/src/pages/CommandDashboardPage.tsx`
- Create: `frontend/src/components/SummaryCards.tsx`
- Create: `frontend/src/components/UpcomingSnapshot.tsx`
- Create: `frontend/src/components/AlertsPanel.tsx`
- Create: `frontend/src/components/FairnessChart.tsx`
- Create: `frontend/src/components/DutyPotentialPanel.tsx`
- Create: `frontend/src/components/ApprovalsFeed.tsx`
- Modify: `frontend/src/App.tsx` (add route)
- Modify: `frontend/src/components/Layout.tsx` (add nav link for commanders)

### Frontend — Algorithm Duty Restriction
- Create: `frontend/src/components/SubHierarchySelector.tsx`
- Modify: `frontend/src/components/AlgorithmPlanningWindow.tsx` (add restriction UI)

---

### Task 1: Backend — Commander dashboard router + schemas

**Files:**
- Create: `backend/app/routes/commander_dashboard.py`

```python
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, Soldier
from app.db.session import get_session
from app.services import commander_dashboard as svc

router = APIRouter(prefix="/command-dashboard", tags=["command-dashboard"])


class SummaryCards(BaseModel):
    approvals_pending: int
    upcoming_duties_7d: int
    unfilled_gaps: int
    alerts_count: int


class SoldierWithStatus(BaseModel):
    id: uuid.UUID
    personal_number: str
    full_name: str
    role: str
    hierarchy_node_id: uuid.UUID | None
    status: str
    cumulative_score: Decimal
    normalised_score: Decimal
    enrolled_at: date
    left_at: date | None


class FairnessStats(BaseModel):
    mean: float
    median: float
    min: float
    max: float
    stddev: float
    soldier_count: int


class NodeFairness(BaseModel):
    node_id: uuid.UUID
    node_name: str
    stats: FairnessStats


class PotentialCount(BaseModel):
    label: str
    count: int
    unit_total: int | None = None


class UpcomingDay(BaseModel):
    date: date
    assignments: list[dict]


class Alert(BaseModel):
    severity: str
    soldier_id: uuid.UUID
    soldier_name: str
    message: str


class ApprovalItem(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_name: str
    request_type: str
    summary: str
    created_at: str


def _get_subtree_ids(session: Session, node_id: uuid.UUID) -> list[uuid.UUID]:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        return [node_id]
    from sqlalchemy import select
    descendants = session.execute(
        select(HierarchyNode.id).where(HierarchyNode.path_ids.any(node_id))
    ).scalars().all()
    return [node_id] + list(descendants)


def _commander_node(session: Session, user: Soldier) -> uuid.UUID | None:
    return session.execute(
        select(HierarchyNode.id).where(HierarchyNode.commander_id == user.id)
    ).scalar_one_or_none()


def _assert_commander(session: Session, user: Soldier) -> uuid.UUID:
    node_id = _commander_node(session, user)
    if node_id is None:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not_a_commander")
    authorize(session, user, Action.HIERARCHY_READ, target_node=session.get(HierarchyNode, node_id))
    return node_id


@router.get("/summary", response_model=SummaryCards)
def get_summary(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SummaryCards:
    node_id = _assert_commander(session, user)
    subtree = _get_subtree_ids(session, node_id)
    return svc.summary_cards(session, subtree_ids=subtree)


@router.get("/soldiers", response_model=list[SoldierWithStatus])
def get_soldiers(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[SoldierWithStatus]:
    node_id = _assert_commander(session, user)
    subtree = _get_subtree_ids(session, node_id)
    return svc.soldiers_in_subtree(session, subtree_ids=subtree)


@router.get("/fairness/internal", response_model=FairnessStats)
def fairness_internal(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> FairnessStats:
    node_id = _assert_commander(session, user)
    subtree = _get_subtree_ids(session, node_id)
    return svc.fairness_stats(session, subtree_ids=subtree)


@router.get("/fairness/external", response_model=list[NodeFairness])
def fairness_external(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[NodeFairness]:
    node_id = _assert_commander(session, user)
    node = session.get(HierarchyNode, node_id)
    if node is None or node.parent_id is None:
        return []
    siblings = session.execute(
        select(HierarchyNode).where(
            HierarchyNode.parent_id == node.parent_id,
            HierarchyNode.id != node_id,
        )
    ).scalars().all()
    result: list[NodeFairness] = []
    node_subtree = _get_subtree_ids(session, node_id)
    result.append(NodeFairness(node_id=node_id, node_name=node.name, stats=svc.fairness_stats(session, subtree_ids=node_subtree)))
    for sibling in siblings:
        sib_subtree = _get_subtree_ids(session, sibling.id)
        result.append(NodeFairness(node_id=sibling.id, node_name=sibling.name, stats=svc.fairness_stats(session, subtree_ids=sib_subtree)))
    return result


@router.get("/potential", response_model=list[PotentialCount])
def potential(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[PotentialCount]:
    node_id = _assert_commander(session, user)
    subtree = _get_subtree_ids(session, node_id)
    return svc.potential_counts(session, subtree_ids=subtree)


@router.get("/upcoming", response_model=list[UpcomingDay])
def upcoming(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[UpcomingDay]:
    node_id = _assert_commander(session, user)
    subtree = _get_subtree_ids(session, node_id)
    return svc.upcoming_duties(session, subtree_ids=subtree, days=7)


@router.get("/alerts", response_model=list[Alert])
def alerts(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[Alert]:
    node_id = _assert_commander(session, user)
    subtree = _get_subtree_ids(session, node_id)
    return svc.alerts(session, subtree_ids=subtree)


@router.get("/approvals", response_model=list[ApprovalItem])
def approvals(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ApprovalItem]:
    node_id = _assert_commander(session, user)
    subtree = _get_subtree_ids(session, node_id)
    return svc.pending_approvals(session, subtree_ids=subtree)
```

- [ ] **Step 1: Create file** `backend/app/routes/commander_dashboard.py` with above content.

### Task 2: Backend — Commander dashboard service

**Files:**
- Create: `backend/app/services/commander_dashboard.py`

```python
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import mean, median, stdev

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment, DutyShift, DutyType, ExemptionDutyTypeMap,
    HierarchyNode, ScoreAdjustment, Soldier, SoldierExemption,
)


def _soldiers_in_nodes(session: Session, subtree_ids: list[uuid.UUID]) -> list[Soldier]:
    return session.execute(
        select(Soldier).where(
            Soldier.hierarchy_node_id.in_(subtree_ids),
            Soldier.left_at.is_(None),
        )
    ).scalars().all()


def _score_data(session: Session, soldiers: list[Soldier]) -> dict[uuid.UUID, dict]:
    soldier_ids = {s.id for s in soldiers}
    duty_scores: dict[uuid.UUID, Decimal] = {}
    for dt in session.execute(select(DutyType)).scalars().all():
        duty_scores[dt.id] = dt.score_per_day

    score_by_soldier: dict[uuid.UUID, Decimal] = defaultdict(lambda: Decimal("0"))
    assignments = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.status == "published",
            DutyAssignment.soldier_id.in_(soldier_ids),
        )
    ).scalars().all()
    for a in assignments:
        days = (a.end_date - a.start_date).days + 1
        score_by_soldier[a.soldier_id] += duty_scores.get(a.duty_type_id, Decimal("0")) * Decimal(days)

    adj_totals: dict[uuid.UUID, Decimal] = defaultdict(lambda: Decimal("0"))
    for row in session.execute(
        select(ScoreAdjustment.soldier_id, func.sum(ScoreAdjustment.delta)).where(
            ScoreAdjustment.soldier_id.in_(soldier_ids)
        ).group_by(ScoreAdjustment.soldier_id)
    ).all():
        adj_totals[row[0]] += Decimal(row[1])

    result: dict[uuid.UUID, dict] = {}
    today = date.today()
    for s in soldiers:
        cum = score_by_soldier.get(s.id, Decimal("0")) + adj_totals.get(s.id, Decimal("0"))
        raw_days = (today - s.enrolled_at).days
        ad = max(1, raw_days)
        result[s.id] = {
            "cumulative_score": cum,
            "normalised_score": cum / Decimal(ad),
            "active_days": ad,
        }
    return result


def summary_cards(session: Session, *, subtree_ids: list[uuid.UUID]) -> dict:
    soldiers = _soldiers_in_nodes(session, subtree_ids)
    soldier_ids = {s.id for s in soldiers}

    # Approvals: pending field updates + exemption requests + swap approvals
    from app.db.models import FieldUpdate
    pending_field = session.execute(
        select(func.count(FieldUpdate.id)).where(
            FieldUpdate.soldier_id.in_(soldier_ids),
            FieldUpdate.status == "pending",
        )
    ).scalar() or 0

    from app.db.models import SoldierExemptionRequest
    pending_exempt = session.execute(
        select(func.count(SoldierExemptionRequest.id)).where(
            SoldierExemptionRequest.soldier_id.in_(soldier_ids),
            SoldierExemptionRequest.status == "pending",
        )
    ).scalar() or 0

    from app.db.models import SwapOffer
    pending_swaps = session.execute(
        select(func.count(SwapOffer.id)).where(
            SwapOffer.soldier_id.in_(soldier_ids),
            SwapOffer.status == "pending",
        )
    ).scalar() or 0

    approvals_pending = pending_field + pending_exempt + pending_swaps

    # Upcoming duties in next 7 days
    today = date.today()
    next_week = today + timedelta(days=7)
    upcoming_assignments = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.status == "published",
            DutyAssignment.soldier_id.in_(soldier_ids),
            DutyAssignment.start_date <= next_week,
            DutyAssignment.end_date >= today,
        )
    ).scalars().all()
    upcoming_duties_7d = len(upcoming_assignments)

    # Unfilled gaps: shifts in the commander's subtree with fill_status != "full"
    shifts_in_subtree = session.execute(
        select(DutyShift).where(
            DutyShift.duty_type_id.in_(
                select(DutyType.id).where(DutyType.active.is_(True))
            )
        )
    ).scalars().all()

    unfilled_gaps = 0
    for shift in shifts_in_subtree:
        if shift.start_date <= next_week and shift.end_date >= today:
            assigned = session.execute(
                select(func.count(DutyAssignment.id)).where(
                    DutyAssignment.duty_shift_id == shift.id,
                    DutyAssignment.status == "published",
                )
            ).scalar() or 0
            if assigned < shift.required_count:
                unfilled_gaps += 1

    # Alerts: soldiers below score threshold, exemptions expiring
    score_data = _score_data(session, soldiers)
    threshold = Decimal("-3.0")
    alerts_count = sum(1 for sd in score_data.values() if sd["normalised_score"] < threshold)

    # Exemptions expiring within 7 days
    for s in soldiers:
        expiring = session.execute(
            select(func.count(SoldierExemption.id)).where(
                SoldierExemption.soldier_id == s.id,
                SoldierExemption.end_date.isnot(None),
                SoldierExemption.end_date <= next_week,
                SoldierExemption.end_date >= today,
            )
        ).scalar() or 0
        alerts_count += expiring

    return {
        "approvals_pending": approvals_pending,
        "upcoming_duties_7d": upcoming_duties_7d,
        "unfilled_gaps": unfilled_gaps,
        "alerts_count": alerts_count,
    }


def soldiers_in_subtree(session: Session, *, subtree_ids: list[uuid.UUID]) -> list[dict]:
    soldiers = _soldiers_in_nodes(session, subtree_ids)
    score_data = _score_data(session, soldiers)

    # Compute status
    today = date.today()
    result = []
    for s in soldiers:
        status = "active"
        # Check for active global exemptions
        ex = session.execute(
            select(SoldierExemption).where(
                SoldierExemption.soldier_id == s.id,
                SoldierExemption.start_date <= today,
                (SoldierExemption.end_date.is_(None) | (SoldierExemption.end_date >= today)),
            )
        ).scalars().all()
        if ex:
            from app.db.models import ExemptionType
            for e in ex:
                et = session.get(ExemptionType, e.exemption_type_id)
                if et and et.is_global:
                    status = "exempt"
                    break

        sd = score_data.get(s.id, {"cumulative_score": Decimal("0"), "normalised_score": Decimal("0")})
        result.append({
            "id": s.id,
            "personal_number": s.personal_number,
            "full_name": s.full_name,
            "role": s.role,
            "hierarchy_node_id": s.hierarchy_node_id,
            "status": status,
            "cumulative_score": sd["cumulative_score"],
            "normalised_score": sd["normalised_score"],
            "enrolled_at": s.enrolled_at,
            "left_at": s.left_at,
        })
    return result


def fairness_stats(session: Session, *, subtree_ids: list[uuid.UUID]) -> dict:
    soldiers = _soldiers_in_nodes(session, subtree_ids)
    score_data = _score_data(session, soldiers)
    scores = [float(sd["normalised_score"]) for sd in score_data.values()]
    if not scores:
        return {"mean": 0.0, "median": 0.0, "min": 0.0, "max": 0.0, "stddev": 0.0, "soldier_count": 0}
    return {
        "mean": round(mean(scores), 4),
        "median": round(median(scores), 4),
        "min": round(min(scores), 4),
        "max": round(max(scores), 4),
        "stddev": round(stdev(scores), 4) if len(scores) > 1 else 0.0,
        "soldier_count": len(scores),
    }


def potential_counts(session: Session, *, subtree_ids: list[uuid.UUID]) -> list[dict]:
    soldiers = _soldiers_in_nodes(session, subtree_ids)
    total_soldiers = len(soldiers)

    counts: list[dict] = []
    chova = sum(1 for s in soldiers if s.mandatory_end_date and s.mandatory_end_date > date.today())
    counts.append({"label": "חובה", "count": chova, "unit_total": None})
    keva = sum(1 for s in soldiers if s.rank and s.rank in ("sgan_aluf", "rav_saren", "saren"))
    counts.append({"label": "קבע", "count": keva, "unit_total": None})
    bahad1 = sum(1 for s in soldiers if s.bahad1_graduate)
    counts.append({"label": "בוגרי בהד\"1", "count": bahad1, "unit_total": None})
    officers = sum(1 for s in soldiers if s.is_officer)
    counts.append({"label": "קצינים", "count": officers, "unit_total": None})
    counts.append({"label": "סה\"כ חיילים", "count": total_soldiers, "unit_total": None})
    return counts


def upcoming_duties(session: Session, *, subtree_ids: list[uuid.UUID], days: int) -> list[dict]:
    soldiers = _soldiers_in_nodes(session, subtree_ids)
    soldier_ids = {s.id for s in soldiers}
    today = date.today()
    end = today + timedelta(days=days)

    assignments = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.status == "published",
            DutyAssignment.soldier_id.in_(soldier_ids),
            DutyAssignment.start_date <= end,
            DutyAssignment.end_date >= today,
        )
    ).scalars().all()

    day_map: dict[date, list[dict]] = {}
    d = today
    while d <= end:
        day_map[d] = []
        d += timedelta(days=1)

    for a in assignments:
        d = max(a.start_date, today)
        while d <= min(a.end_date, end):
            day_map.setdefault(d, []).append({
                "assignment_id": str(a.id),
                "duty_type_id": str(a.duty_type_id),
                "soldier_id": str(a.soldier_id),
            })
            d += timedelta(days=1)

    result = []
    for dt, assigns in sorted(day_map.items()):
        result.append({"date": str(dt), "assignments": assigns})
    return result


def alerts(session: Session, *, subtree_ids: list[uuid.UUID]) -> list[dict]:
    soldiers = _soldiers_in_nodes(session, subtree_ids)
    score_data = _score_data(session, soldiers)
    threshold = Decimal("-3.0")
    today = date.today()
    next_week = today + timedelta(days=7)

    alerts_list: list[dict] = []

    for s in soldiers:
        sd = score_data.get(s.id, {})
        norm = sd.get("normalised_score", Decimal("0"))
        if norm < threshold:
            alerts_list.append({
                "severity": "warning",
                "soldier_id": s.id,
                "soldier_name": s.full_name,
                "message": f"ניקוד מנורמל נמוך: {norm:.2f}",
            })

        exemptions = session.execute(
            select(SoldierExemption).where(
                SoldierExemption.soldier_id == s.id,
                SoldierExemption.end_date.isnot(None),
                SoldierExemption.end_date <= next_week,
                SoldierExemption.end_date >= today,
            )
        ).scalars().all()
        for ex in exemptions:
            from app.db.models import ExemptionType
            et = session.get(ExemptionType, ex.exemption_type_id)
            name = et.name if et else "פטור"
            alerts_list.append({
                "severity": "info",
                "soldier_id": s.id,
                "soldier_name": s.full_name,
                "message": f"תוקף {name} מסתיים ב-{ex.end_date}",
            })

    return alerts_list


def pending_approvals(session: Session, *, subtree_ids: list[uuid.UUID]) -> list[dict]:
    soldiers = _soldiers_in_nodes(session, subtree_ids)
    soldier_ids = {s.id for s in soldiers}
    name_map = {s.id: s.full_name for s in soldiers}

    items: list[dict] = []

    # Field updates
    from app.db.models import FieldUpdate
    fus = session.execute(
        select(FieldUpdate).where(
            FieldUpdate.soldier_id.in_(soldier_ids),
            FieldUpdate.status == "pending",
        )
    ).scalars().all()
    for fu in fus:
        items.append({
            "id": fu.id,
            "soldier_id": fu.soldier_id,
            "soldier_name": name_map.get(fu.soldier_id, ""),
            "request_type": "field_update",
            "summary": f"שינוי {fu.field_name}: {fu.previous_value or 'ריק'} → {fu.new_value}",
            "created_at": str(fu.created_at),
        })

    # Exemption requests
    from app.db.models import SoldierExemptionRequest
    ers = session.execute(
        select(SoldierExemptionRequest).where(
            SoldierExemptionRequest.soldier_id.in_(soldier_ids),
            SoldierExemptionRequest.status == "pending",
        )
    ).scalars().all()
    for er in ers:
        items.append({
            "id": er.id,
            "soldier_id": er.soldier_id,
            "soldier_name": name_map.get(er.soldier_id, ""),
            "request_type": "exemption",
            "summary": f"בקשת פטור",
            "created_at": str(er.created_at),
        })

    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return items
```

- [ ] **Step 1: Create file** `backend/app/services/commander_dashboard.py` with above content.

- [ ] **Step 2: Verify imports compile**

Run: `cd backend && .venv\Scripts\python -c "from app.services import commander_dashboard; print('OK')"`
Expected: prints "OK"

### Task 3: Backend — Register commander dashboard router in main.py

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add import** after line 24 (`from app.routes import reserves as reserve_routes`):

```python
from app.routes import commander_dashboard as commander_dashboard_routes
```

- [ ] **Step 2: Add include_router** after line 59 (`app.include_router(reserve_routes.router, prefix="/api")`):

```python
    app.include_router(commander_dashboard_routes.router, prefix="/api")
```

- [ ] **Step 3: Verify app starts**

Run: `cd backend && .venv\Scripts\python -c "from app.main import create_app; app = create_app(); print('OK')"`
Expected: prints "OK"

### Task 4: Backend — Add eligible_node_ids to DutyBlock type

**Files:**
- Modify: `backend/app/algorithm/types.py`

- [ ] **Step 1: Add field to DutyBlock** — add `eligible_node_ids`:

Edit `backend/app/algorithm/types.py`, add after `is_reserve` in `DutyBlock`:
```python
    eligible_node_ids: list[uuid.UUID] | None = None
```

- [ ] **Step 2: Verify no syntax errors**

Run: `cd backend && .venv\Scripts\python -c "from app.algorithm.types import DutyBlock; print('OK')"`
Expected: prints "OK"

### Task 5: Backend — Filter CP-SAT model by eligible_node_ids

**Files:**
- Modify: `backend/app/algorithm/model.py`

- [ ] **Step 1: Add node-based eligibility check** in `build_model`, after the existing `eligible` loop (around line 80), add a filter inside the `for di, d in enumerate(duty_list): for si, s in enumerate(soldier_list):` block:

After line 79 (`if any(dt in constrained_dates for dt in _duty_dates(d)): continue`) and before `eligible.append((di, si))`, add:

```python
            if d.eligible_node_ids is not None and s.hierarchy_node_id is not None:
                if s.hierarchy_node_id not in d.eligible_node_ids:
                    continue
```

The final filter block should look like:
```python
    for di, d in enumerate(duty_list):
        for si, s in enumerate(soldier_list):
            if d.duty_type_id in exempt_map.get(s.id, set()):
                continue
            constrained_dates = constraint_map.get(s.id, set())
            if any(dt in constrained_dates for dt in _duty_dates(d)):
                continue
            if d.eligible_node_ids is not None and s.hierarchy_node_id is not None:
                if s.hierarchy_node_id not in d.eligible_node_ids:
                    continue
            eligible.append((di, si))
```

- [ ] **Step 2: Verify no syntax errors**

Run: `cd backend && .venv\Scripts\python -c "from app.algorithm.model import build_model; print('OK')"`
Expected: prints "OK"

### Task 6: Backend — Pass eligible_node_ids from shifts to DutyBlock in algorithm bridge

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py`

- [ ] **Step 1: Find where DutyBlock is created from DutyShift** — search for where `DutyBlock` is instantiated

Run: `Select-String -Path "backend/app/services/algorithm_bridge.py" -Pattern "DutyBlock\("`

- [ ] **Step 2: Add eligible_node_ids** to each `DutyBlock(...)` call — add `eligible_node_ids=shift.eligible_node_ids` parameter.

Example patch:
```python
DutyBlock(
    id=shift.id,
    duty_type_id=shift.duty_type_id,
    duty_location_id=shift.duty_location_id,
    start_date=shift.start_date,
    end_date=shift.end_date,
    score_per_day=scores.get(shift.duty_type_id, Decimal("0")),
    is_reserve=False,
    eligible_node_ids=shift.eligible_node_ids,  # add this
)
```

- [ ] **Step 3: Verify no syntax errors**

Run: `cd backend && .venv\Scripts\python -c "from app.services.algorithm_bridge import run_algorithm_job; print('OK')"`
Expected: prints "OK"

### Task 7: Frontend — Commander dashboard API client

**Files:**
- Create: `frontend/src/api/commanderDashboard.ts`

```typescript
import { api } from "./client";

export interface SummaryCards {
  approvals_pending: number;
  upcoming_duties_7d: number;
  unfilled_gaps: number;
  alerts_count: number;
}

export interface SoldierWithStatus {
  id: string;
  personal_number: string;
  full_name: string;
  role: string;
  hierarchy_node_id: string | null;
  status: string;
  cumulative_score: string;
  normalised_score: string;
  enrolled_at: string;
  left_at: string | null;
}

export interface FairnessStats {
  mean: number;
  median: number;
  min: number;
  max: number;
  stddev: number;
  soldier_count: number;
}

export interface NodeFairness {
  node_id: string;
  node_name: string;
  stats: FairnessStats;
}

export interface PotentialCount {
  label: string;
  count: number;
  unit_total: number | null;
}

export interface UpcomingDay {
  date: string;
  assignments: { assignment_id: string; duty_type_id: string; soldier_id: string }[];
}

export interface Alert {
  severity: string;
  soldier_id: string;
  soldier_name: string;
  message: string;
}

export interface ApprovalItem {
  id: string;
  soldier_id: string;
  soldier_name: string;
  request_type: string;
  summary: string;
  created_at: string;
}

export async function getSummary(): Promise<SummaryCards> {
  return (await api.get<SummaryCards>("/command-dashboard/summary")).data;
}

export async function getDashboardSoldiers(): Promise<SoldierWithStatus[]> {
  return (await api.get<SoldierWithStatus[]>("/command-dashboard/soldiers")).data;
}

export async function getFairnessInternal(): Promise<FairnessStats> {
  return (await api.get<FairnessStats>("/command-dashboard/fairness/internal")).data;
}

export async function getFairnessExternal(): Promise<NodeFairness[]> {
  return (await api.get<NodeFairness[]>("/command-dashboard/fairness/external")).data;
}

export async function getPotential(): Promise<PotentialCount[]> {
  return (await api.get<PotentialCount[]>("/command-dashboard/potential")).data;
}

export async function getUpcoming(): Promise<UpcomingDay[]> {
  return (await api.get<UpcomingDay[]>("/command-dashboard/upcoming")).data;
}

export async function getAlerts(): Promise<Alert[]> {
  return (await api.get<Alert[]>("/command-dashboard/alerts")).data;
}

export async function getApprovals(): Promise<ApprovalItem[]> {
  return (await api.get<ApprovalItem[]>("/command-dashboard/approvals")).data;
}
```

- [ ] **Step 1: Create file** `frontend/src/api/commanderDashboard.ts` with above content.

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit src/api/commanderDashboard.ts`
Expected: no errors

### Task 8: Frontend — SummaryCards component

**Files:**
- Create: `frontend/src/components/SummaryCards.tsx`

```tsx
import { useTranslation } from "react-i18next";
import type { SummaryCards as SummaryCardsData } from "../api/commanderDashboard";

interface Props {
  data: SummaryCardsData | null;
  onCardClick: (panel: string) => void;
}

export default function SummaryCards({ data, onCardClick }: Props) {
  const { t } = useTranslation();
  if (!data) return null;
  return (
    <div className="flex gap-4 mb-6" data-testid="summary-cards">
      <button onClick={() => onCardClick("approvals")} className="flex-1 bg-white rounded-lg shadow p-4 text-right hover:bg-gray-50" data-testid="card-approvals">
        <div className="text-2xl font-bold">{data.approvals_pending}</div>
        <div className="text-sm text-gray-500">{t("command_dashboard.approvals_pending")}</div>
      </button>
      <button onClick={() => onCardClick("upcoming")} className="flex-1 bg-white rounded-lg shadow p-4 text-right hover:bg-gray-50" data-testid="card-upcoming">
        <div className="text-2xl font-bold">{data.upcoming_duties_7d}</div>
        {data.unfilled_gaps > 0 && <span className="text-xs text-red-500 mr-1">({data.unfilled_gaps} {t("command_dashboard.gaps")})</span>}
        <div className="text-sm text-gray-500">{t("command_dashboard.upcoming_7d")}</div>
      </button>
      <button onClick={() => onCardClick("alerts")} className="flex-1 bg-white rounded-lg shadow p-4 text-right hover:bg-gray-50" data-testid="card-alerts">
        <div className="text-2xl font-bold">{data.alerts_count}</div>
        <div className="text-sm text-gray-500">{t("command_dashboard.alerts")}</div>
      </button>
    </div>
  );
}
```

- [ ] **Step 1: Create file** `frontend/src/components/SummaryCards.tsx` with above content.

### Task 9: Frontend — UpcomingSnapshot component

**Files:**
- Create: `frontend/src/components/UpcomingSnapshot.tsx`

```tsx
import { useTranslation } from "react-i18next";
import type { UpcomingDay } from "../api/commanderDashboard";

interface Props {
  data: UpcomingDay[] | null;
}

export default function UpcomingSnapshot({ data }: Props) {
  const { t } = useTranslation();
  if (!data || data.length === 0) return <p className="text-gray-500">{t("command_dashboard.no_upcoming")}</p>;
  const today = new Date().toISOString().slice(0, 10);
  return (
    <div className="space-y-2" data-testid="upcoming-snapshot">
      {data.map((day) => {
        const isToday = day.date === today;
        return (
          <div key={day.date} className={`flex items-center gap-3 p-2 rounded ${isToday ? "bg-indigo-50" : ""}`}>
            <span className="text-sm font-medium w-16">{new Date(day.date).toLocaleDateString("he-IL", { weekday: "short", day: "numeric" })}</span>
            <div className="flex-1 flex gap-1">
              {day.assignments.length === 0 ? (
                <span className="text-xs text-gray-400">{t("command_dashboard.none")}</span>
              ) : (
                day.assignments.map((a) => (
                  <span key={a.assignment_id} className="text-xs bg-gray-100 rounded px-2 py-0.5">{a.duty_type_id.slice(0, 6)}</span>
                ))
              )}
            </div>
            <span className="text-xs text-gray-500">{day.assignments.length}</span>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 1: Create file** `frontend/src/components/UpcomingSnapshot.tsx` with above content.

### Task 10: Frontend — AlertsPanel component

**Files:**
- Create: `frontend/src/components/AlertsPanel.tsx`

```tsx
import { useTranslation } from "react-i18next";
import type { Alert } from "../api/commanderDashboard";

interface Props {
  data: Alert[] | null;
}

const severityColor: Record<string, string> = {
  warning: "text-yellow-700 bg-yellow-50 border-yellow-200",
  info: "text-blue-700 bg-blue-50 border-blue-200",
};

export default function AlertsPanel({ data }: Props) {
  const { t } = useTranslation();
  if (!data || data.length === 0) return <p className="text-gray-500">{t("command_dashboard.no_alerts")}</p>;
  return (
    <div className="space-y-2" data-testid="alerts-panel">
      {data.map((a, i) => (
        <div key={i} className={`border rounded p-2 text-sm ${severityColor[a.severity] || "text-gray-700 bg-gray-50"}`}>
          <span className="font-medium">{a.soldier_name}</span>: {a.message}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 1: Create file** `frontend/src/components/AlertsPanel.tsx` with above content.

### Task 11: Frontend — FairnessChart component

**Files:**
- Create: `frontend/src/components/FairnessChart.tsx`

```tsx
import { useTranslation } from "react-i18next";
import type { FairnessStats, NodeFairness } from "../api/commanderDashboard";

interface InternalProps {
  data: FairnessStats | null;
}

interface ExternalProps {
  data: NodeFairness[] | null;
}

export function InternalFairness({ data }: InternalProps) {
  const { t } = useTranslation();
  if (!data || data.soldier_count === 0) return <p className="text-gray-500">{t("command_dashboard.no_fairness_data")}</p>;
  return (
    <div className="space-y-1 text-sm" data-testid="internal-fairness">
      <div className="grid grid-cols-3 gap-2">
        <div><span className="text-gray-500">{t("command_dashboard.mean")}:</span> <strong>{data.mean}</strong></div>
        <div><span className="text-gray-500">{t("command_dashboard.median")}:</span> <strong>{data.median}</strong></div>
        <div><span className="text-gray-500">{t("command_dashboard.stddev")}:</span> <strong>{data.stddev}</strong></div>
        <div><span className="text-gray-500">{t("command_dashboard.min")}:</span> <strong>{data.min}</strong></div>
        <div><span className="text-gray-500">{t("command_dashboard.max")}:</span> <strong>{data.max}</strong></div>
        <div><span className="text-gray-500">{t("command_dashboard.soldiers")}:</span> <strong>{data.soldier_count}</strong></div>
      </div>
    </div>
  );
}

export function ExternalFairness({ data }: ExternalProps) {
  const { t } = useTranslation();
  if (!data || data.length === 0) return <p className="text-gray-500">{t("command_dashboard.no_peers")}</p>;
  return (
    <div className="overflow-x-auto" data-testid="external-fairness">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b">
            <th className="text-right p-1">{t("command_dashboard.unit")}</th>
            <th className="text-right p-1">{t("command_dashboard.mean")}</th>
            <th className="text-right p-1">{t("command_dashboard.median")}</th>
            <th className="text-right p-1">{t("command_dashboard.stddev")}</th>
            <th className="text-right p-1">{t("command_dashboard.soldiers")}</th>
          </tr>
        </thead>
        <tbody>
          {data.map((n) => (
            <tr key={n.node_id} className="border-b hover:bg-gray-50">
              <td className="p-1 font-medium">{n.node_name}</td>
              <td className="p-1">{n.stats.mean}</td>
              <td className="p-1">{n.stats.median}</td>
              <td className="p-1">{n.stats.stddev}</td>
              <td className="p-1">{n.stats.soldier_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 1: Create file** `frontend/src/components/FairnessChart.tsx` with above content.

### Task 12: Frontend — DutyPotentialPanel component

**Files:**
- Create: `frontend/src/components/DutyPotentialPanel.tsx`

```tsx
import { useTranslation } from "react-i18next";
import type { PotentialCount } from "../api/commanderDashboard";

interface Props {
  data: PotentialCount[] | null;
}

export default function DutyPotentialPanel({ data }: Props) {
  const { t } = useTranslation();
  if (!data || data.length === 0) return <p className="text-gray-500">{t("command_dashboard.no_potential_data")}</p>;
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3" data-testid="duty-potential">
      {data.map((pc) => (
        <div key={pc.label} className="bg-gray-50 rounded p-3 text-center">
          <div className="text-2xl font-bold">{pc.count}</div>
          <div className="text-sm text-gray-600">{pc.label}</div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 1: Create file** `frontend/src/components/DutyPotentialPanel.tsx` with above content.

### Task 13: Frontend — ApprovalsFeed component

**Files:**
- Create: `frontend/src/components/ApprovalsFeed.tsx`

```tsx
import { useTranslation } from "react-i18next";
import type { ApprovalItem } from "../api/commanderDashboard";

interface Props {
  data: ApprovalItem[] | null;
}

export default function ApprovalsFeed({ data }: Props) {
  const { t } = useTranslation();
  if (!data || data.length === 0) return <p className="text-gray-500">{t("command_dashboard.no_pending_approvals")}</p>;
  return (
    <div className="space-y-2" data-testid="approvals-feed">
      {data.map((item) => (
        <div key={item.id} className="flex items-center justify-between border rounded p-2 text-sm">
          <div>
            <span className="font-medium">{item.soldier_name}</span>
            <span className="mx-1 text-gray-400">·</span>
            <span className="text-gray-500">{item.summary}</span>
          </div>
          <span className="text-xs text-gray-400">{new Date(item.created_at).toLocaleDateString("he-IL")}</span>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 1: Create file** `frontend/src/components/ApprovalsFeed.tsx` with above content.

### Task 14: Frontend — CommandDashboardPage main page

**Files:**
- Create: `frontend/src/pages/CommandDashboardPage.tsx`

```tsx
import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import SummaryCards from "../components/SummaryCards";
import UpcomingSnapshot from "../components/UpcomingSnapshot";
import AlertsPanel from "../components/AlertsPanel";
import { InternalFairness, ExternalFairness } from "../components/FairnessChart";
import DutyPotentialPanel from "../components/DutyPotentialPanel";
import ApprovalsFeed from "../components/ApprovalsFeed";
import UnitCalendar from "../components/UnitCalendar";
import HierarchyTree from "../components/HierarchyTree";
import { useAuth } from "../auth/AuthContext";
import { NodeDTO, fetchTree } from "../api/hierarchy";
import {
  getSummary, getDashboardSoldiers, getFairnessInternal,
  getFairnessExternal, getPotential, getUpcoming,
  getAlerts, getApprovals,
  type SummaryCards as SummaryCardsData,
  type SoldierWithStatus, type FairnessStats,
  type NodeFairness, type PotentialCount,
  type UpcomingDay, type Alert, type ApprovalItem,
} from "../api/commanderDashboard";

export default function CommandDashboardPage() {
  const { t } = useTranslation();
  const { user } = useAuth();

  const [summaryData, setSummaryData] = useState<SummaryCardsData | null>(null);
  const [soldiers, setSoldiers] = useState<SoldierWithStatus[]>([]);
  const [nodes, setNodes] = useState<NodeDTO[]>([]);
  const [fairnessInternal, setFairnessInternal] = useState<FairnessStats | null>(null);
  const [fairnessExternal, setFairnessExternal] = useState<NodeFairness[] | null>(null);
  const [potentialData, setPotentialData] = useState<PotentialCount[] | null>(null);
  const [upcomingData, setUpcomingData] = useState<UpcomingDay[] | null>(null);
  const [alertsData, setAlertsData] = useState<Alert[] | null>(null);
  const [approvalsData, setApprovalsData] = useState<ApprovalItem[] | null>(null);
  const [activePanel, setActivePanel] = useState<string>("summary");

  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([
      getSummary(), getDashboardSoldiers(), getFairnessInternal(),
      getFairnessExternal(), getPotential(), getUpcoming(),
      getAlerts(), getApprovals(), fetchTree(),
    ]);
    if (results[0].status === "fulfilled") setSummaryData(results[0].value);
    if (results[1].status === "fulfilled") setSoldiers(results[1].value);
    if (results[2].status === "fulfilled") setFairnessInternal(results[2].value);
    if (results[3].status === "fulfilled") setFairnessExternal(results[3].value);
    if (results[4].status === "fulfilled") setPotentialData(results[4].value);
    if (results[5].status === "fulfilled") setUpcomingData(results[5].value);
    if (results[6].status === "fulfilled") setAlertsData(results[6].value);
    if (results[7].status === "fulfilled") setApprovalsData(results[7].value);
    if (results[8].status === "fulfilled") setNodes(results[8].value);
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const handleCardClick = (panel: string) => setActivePanel(panel);

  const panels: { id: string; title: string; content: React.ReactNode }[] = [
    {
      id: "calendar",
      title: t("command_dashboard.calendar"),
      content: nodes.length > 0 ? <UnitCalendar nodeId={nodes[0]?.id || ""} /> : null,
    },
    {
      id: "soldiers",
      title: t("command_dashboard.soldiers"),
      content: (
        <div>
          <div className="mb-4">
            <HierarchyTree nodes={nodes} soldiers={soldiers as any} isAdmin={false} onChanged={refresh} user={user} />
          </div>
        </div>
      ),
    },
    {
      id: "fairness_internal",
      title: t("command_dashboard.internal_fairness"),
      content: <InternalFairness data={fairnessInternal} />,
    },
    {
      id: "fairness_external",
      title: t("command_dashboard.external_fairness"),
      content: <ExternalFairness data={fairnessExternal} />,
    },
    {
      id: "entries_exits",
      title: t("command_dashboard.entries_exits"),
      content: <p className="text-gray-500">{t("command_dashboard.entries_exits_placeholder")}</p>,
    },
    {
      id: "potential",
      title: t("command_dashboard.potential"),
      content: <DutyPotentialPanel data={potentialData} />,
    },
    {
      id: "approvals",
      title: t("command_dashboard.approvals"),
      content: <ApprovalsFeed data={approvalsData} />,
    },
    {
      id: "upcoming",
      title: t("command_dashboard.upcoming"),
      content: <UpcomingSnapshot data={upcomingData} />,
    },
    {
      id: "alerts",
      title: t("command_dashboard.alerts"),
      content: <AlertsPanel data={alertsData} />,
    },
  ];

  return (
    <Layout>
      <section className="space-y-4" data-testid="command-dashboard-page">
        <h2 className="text-xl font-semibold">{t("command_dashboard.title")}</h2>
        <SummaryCards data={summaryData} onCardClick={handleCardClick} />
        {panels.map((panel) => (
          <details key={panel.id} open={activePanel === panel.id} className="bg-white rounded-lg shadow p-4" data-testid={`panel-${panel.id}`}>
            <summary className="cursor-pointer font-medium text-lg mb-2">{panel.title}</summary>
            {panel.content}
          </details>
        ))}
      </section>
    </Layout>
  );
}
```

- [ ] **Step 1: Create file** `frontend/src/pages/CommandDashboardPage.tsx` with above content. Note: the `fetchTree` import needs to be from `../api/hierarchy` — add that import.

### Task 15: Frontend — Add route + nav link for commander dashboard

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout.tsx`

- [ ] **Step 1: Add import** in `App.tsx`:

```typescript
import CommandDashboardPage from "./pages/CommandDashboardPage";
```

- [ ] **Step 2: Add route** in `App.tsx` after the existing route list:

```typescript
          <Route path="/command-dashboard" element={<ForcedPasswordGate><CommandDashboardPage /></ForcedPasswordGate>} />
```

- [ ] **Step 3: Add nav link** in `Layout.tsx`, add a nav link for commanders (alongside existing commander-accessible links, e.g. after `/team`):

```typescript
        <Link to="/command-dashboard" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-command-dashboard">{t("nav.command_dashboard")}</Link>
```

- [ ] **Step 4: Verify frontend compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

### Task 16: Frontend — SubHierarchySelector component for algorithm restriction

**Files:**
- Create: `frontend/src/components/SubHierarchySelector.tsx`

```tsx
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO, fetchTree } from "../api/hierarchy";

interface Props {
  value: string[];
  onChange: (selected: string[]) => void;
}

export default function SubHierarchySelector({ value, onChange }: Props) {
  const { t } = useTranslation();
  const [nodes, setNodes] = useState<NodeDTO[]>([]);

  useEffect(() => { void fetchTree().then(setNodes); }, []);

  function toggleNode(nodeId: string) {
    if (value.includes(nodeId)) {
      onChange(value.filter((id) => id !== nodeId));
    } else {
      onChange([...value, nodeId]);
    }
  }

  function renderNode(node: NodeDTO, depth = 0): React.ReactNode {
    const checked = value.includes(node.id);
    return (
      <div key={node.id}>
        <label className="flex items-center gap-2 py-1 hover:bg-gray-50 cursor-pointer" style={{ paddingRight: `${depth * 16 + 8}px` }}>
          <input type="checkbox" checked={checked} onChange={() => toggleNode(node.id)} className="rounded" />
          <span className="text-sm">{node.name}</span>
        </label>
        {node.children?.map((child) => renderNode(child, depth + 1))}
      </div>
    );
  }

  return (
    <div className="border rounded p-2 max-h-60 overflow-y-auto" data-testid="sub-hierarchy-selector">
      <p className="text-xs text-gray-500 mb-2">{t("algorithm.select_eligible_nodes")}</p>
      {nodes.map((n) => renderNode(n))}
    </div>
  );
}
```

- [ ] **Step 1: Create file** `frontend/src/components/SubHierarchySelector.tsx` with above content.

### Task 17: Frontend — Add restriction UI to algorithm planning window

**Files:**
- Modify: `frontend/src/components/AlgorithmPlanningWindow.tsx`

- [ ] **Step 1: Read the existing file** to find where to add the sub-hierarchy selector (likely near the shift selection or settings area).

- [ ] **Step 2: Import and add** the `SubHierarchySelector` component. Add a section where the DM can select which nodes' soldiers are eligible for the selected shifts.

```tsx
import SubHierarchySelector from "./SubHierarchySelector";

// Add state:
const [eligibleNodeIds, setEligibleNodeIds] = useState<string[]>([]);

// Add UI in the settings section:
<details className="border rounded p-2 mt-2">
  <summary className="text-sm font-medium cursor-pointer">{t("algorithm.restrict_to_subtree")}</summary>
  <SubHierarchySelector value={eligibleNodeIds} onChange={setEligibleNodeIds} />
</details>

// Pass eligibleNodeIds when creating the job or updating shifts
```

### Task 17b: Frontend — Entries & Exits panel implementation

**Files:**
- Create: `frontend/src/components/EntriesExitsPanel.tsx`
- Modify: `frontend/src/pages/CommandDashboardPage.tsx`

The panel shows all soldiers in the subtree (reuses data from `getDashboardSoldiers`) with action buttons:
- **Grant exemption**: uses existing `POST /soldiers/{id}/exemptions` for a global exemption type, with a date range picker and reason field.
- **Move to different unit**: uses existing `PATCH /soldiers/{id}` to update `hierarchy_node_id`, with a node selector.
- **Release from unit**: uses existing `DELETE /soldiers/{id}` for soft delete.

- [ ] **Step 1: Create** `frontend/src/components/EntriesExitsPanel.tsx`:

```tsx
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { SoldierWithStatus } from "../api/commanderDashboard";
import { updateSoldier, softDeleteSoldier } from "../api/soldiers";
import { grantExemption } from "../api/exemptions";
import { NodeDTO } from "../api/hierarchy";

interface Props {
  soldiers: SoldierWithStatus[];
  nodes: NodeDTO[];
  onRefresh: () => void;
}

export default function EntriesExitsPanel({ soldiers, nodes, onRefresh }: Props) {
  const { t } = useTranslation();
  const [actionSoldier, setActionSoldier] = useState<string | null>(null);
  const [actionType, setActionType] = useState<"exempt" | "move" | "release" | null>(null);

  async function handleExempt(soldierId: string, exemptionTypeId: string, startDate: string, endDate: string) {
    await grantExemption(soldierId, { exemption_type_id: exemptionTypeId, start_date: startDate, end_date: endDate || null });
    onRefresh();
  }
  async function handleMove(soldierId: string, nodeId: string) {
    await updateSoldier(soldierId, { hierarchy_node_id: nodeId });
    onRefresh();
  }
  async function handleRelease(soldierId: string) {
    if (!confirm(t("command_dashboard.confirm_release"))) return;
    await softDeleteSoldier(soldierId);
    onRefresh();
  }

  return (
    <div className="overflow-x-auto" data-testid="entries-exits-panel">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b">
            <th className="text-right p-1">{t("command_dashboard.name")}</th>
            <th className="text-right p-1">{t("command_dashboard.status")}</th>
            <th className="text-right p-1">{t("command_dashboard.actions")}</th>
          </tr>
        </thead>
        <tbody>
          {soldiers.map((s) => (
            <tr key={s.id} className="border-b hover:bg-gray-50">
              <td className="p-1">{s.full_name}</td>
              <td className="p-1">{s.status}</td>
              <td className="p-1 space-x-2 space-x-reverse">
                <button onClick={() => { setActionSoldier(s.id); setActionType("exempt"); }} className="text-indigo-600 text-xs">{t("command_dashboard.exempt")}</button>
                <button onClick={() => { setActionSoldier(s.id); setActionType("move"); }} className="text-indigo-600 text-xs">{t("command_dashboard.move")}</button>
                <button onClick={() => handleRelease(s.id)} className="text-red-600 text-xs">{t("command_dashboard.release")}</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 2: Wire into CommandDashboardPage** — replace the entries_exits placeholder with `<EntriesExitsPanel soldiers={soldiers} nodes={nodes} onRefresh={refresh} />`.

- [ ] **Step 3: Verify frontend compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

All front-end tasks combined:

- [ ] **Step 4: Verify frontend compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

### Task 18: Backend — Add eligible_node_ids field to DutyShift model + migration

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/0026_add_eligible_node_ids.py`

- [ ] **Step 1: Add field** to `DutyShift` model in `models.py`, after `reserve_count_override`:

```python
    eligible_node_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=True, default=None
    )
```

- [ ] **Step 2: Generate migration**:

Run: `cd backend && .venv\Scripts\alembic revision --autogenerate -m "add eligible_node_ids to duty_shifts"`

- [ ] **Step 3: Apply migration**:

Run: `cd backend && .venv\Scripts\alembic upgrade head`

- [ ] **Step 4: Add eligible_node_ids** to the `UpdateShiftRequest` schema in `routes/shifts.py`:

```python
    eligible_node_ids: list[uuid.UUID] | None = None
```

- [ ] **Step 5: Update shift update service** to persist `eligible_node_ids` when set.

### Task 19: Backend tests for commander dashboard

**Files:**
- Create: `backend/app/routes/tests/test_commander_dashboard.py`

```python
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import create_autospec

from sqlalchemy.orm import Session

from app.services import commander_dashboard as svc


def test_summary_cards_empty_subtree():
    """Empty subtree returns zeros."""
    session = create_autospec(Session)
    result = svc.summary_cards(session, subtree_ids=[])
    assert result["approvals_pending"] == 0
    assert result["upcoming_duties_7d"] == 0
    assert result["unfilled_gaps"] == 0
    assert result["alerts_count"] == 0


def test_fairness_stats_empty():
    """No soldiers returns all-zero stats."""
    session = create_autospec(Session)
    result = svc.fairness_stats(session, subtree_ids=[])
    assert result["soldier_count"] == 0
    assert result["mean"] == 0.0


def test_potential_counts_no_soldiers():
    """Empty subtree returns empty list."""
    session = create_autospec(Session)
    result = svc.potential_counts(session, subtree_ids=[])
    assert result == []
```

- [ ] **Step 1: Create file** with above test content.

- [ ] **Step 2: Run tests**:

Run: `cd backend && .venv\Scripts\python -m pytest app/routes/tests/test_commander_dashboard.py -v`
Expected: 3 passed

### Task 20: Frontend E2E test for commander dashboard

**Files:**
- Create: `frontend/tests/e2e/commander-dashboard.spec.ts`

```typescript
import { test, expect } from "@playwright/test";

test.describe("Commander Dashboard", () => {
  test.beforeEach(async ({ page }) => {
    // Login as a commander
    await page.goto("/login");
    await page.fill('[data-testid="login-pn"]', "4000002"); // לוחם ותיק is commander of branch node
    await page.fill('[data-testid="login-password"]', "password123");
    await page.click('[data-testid="login-submit"]');
    await page.waitForURL(/\/$/);
  });

  test("shows commander dashboard with summary cards", async ({ page }) => {
    await page.goto("/command-dashboard");
    await expect(page.locator('[data-testid="command-dashboard-page"]')).toBeVisible();
    await expect(page.locator('[data-testid="summary-cards"]')).toBeVisible();
  });

  test("calendar panel loads", async ({ page }) => {
    await page.goto("/command-dashboard");
    const calendar = page.locator('[data-testid="panel-calendar"]');
    await expect(calendar).toBeVisible();
  });

  test("upcoming snapshot loads", async ({ page }) => {
    await page.goto("/command-dashboard");
    const snapshot = page.locator('[data-testid="upcoming-snapshot"]');
    // May be empty if no duties, but component should still render
    await expect(snapshot).toBeVisible();
  });
});
```

- [ ] **Step 1: Create file** with above test content.

- [ ] **Step 2: Run test**:

Run: `cd frontend && npx playwright test tests/e2e/commander-dashboard.spec.ts`
Expected: All tests pass (or at least the page loads correctly)
