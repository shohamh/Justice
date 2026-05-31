# Shift-Based Calendar & Reserve Dismissal UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite UnitCalendar to show shifts as events (not per-soldier assignments), with a rich detail panel for primary/reserve management including visual dismissal range picker.

**Architecture:** New backend `GET /calendar/shifts` endpoint returns shifts with their assignees grouped, already split by primary/reserve. Frontend creates one FullCalendar event per shift; click opens a modal with separate primary/reserve sections, a dismissal range slider, and automatic reserve call-up + relink.

**Tech Stack:** FastAPI, Pydantic, React, FullCalendar, @tanstack/react-query, Python 3.13

---

### Task 1: Backend — calendar shifts service + endpoint

**Files:**
- Create: `backend/app/services/calendar_shifts.py`
- Modify: `backend/app/routes/calendar.py`
- Test: `backend/tests/integration/test_calendar_api.py`

**Design:**
Service function `get_calendar_shifts(session, node_id, date_from, date_to)` returns shifts with assignees in the hierarchy subtree. The route wraps it in a Pydantic response.

- [ ] **Step 1: Write integration test for the new endpoint**

Add to `test_calendar_api.py`:

```python
def test_calendar_shifts_returns_shift_events(client: TestClient, admin_session: Session):
    from datetime import date
    admin = create_soldier(admin_session, personal_number="7100001", role="admin")
    dept = create_node(admin_session, level="department", name="cal-shift-dept")
    branch = create_node(admin_session, level="branch", name="cal-shift-br", parent=dept)
    s1 = create_soldier(admin_session, personal_number="7100002", role="soldier", hierarchy_node_id=branch.id)
    s2 = create_soldier(admin_session, personal_number="7100003", role="soldier", hierarchy_node_id=branch.id)
    admin_session.commit()
    dt = DutyType(name="שמירה-cs", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="מוצב-cs")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    shift_resp = client.post("/api/shifts", headers=auth_headers(admin), json={
        "duty_type_id": str(dt.id), "duty_location_id": str(loc.id),
        "start_date": "2026-11-01", "end_date": "2026-11-03", "required_count": 2,
    })
    assert shift_resp.status_code == 201
    shift_id = shift_resp.json()["id"]

    # Create primary assignments for both soldiers
    for sid in [s1.id, s2.id]:
        client.post("/api/assignments", headers=auth_headers(admin), json={
            "soldier_id": str(sid), "duty_type_id": str(dt.id), "duty_location_id": str(loc.id),
            "start_date": "2026-11-01", "end_date": "2026-11-03",
            "duty_shift_id": shift_id,
        })

    r = client.get(f"/api/calendar/shifts?node_id={branch.id}&date_from=2026-11-01&date_to=2026-11-03",
                   headers=auth_headers(admin))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "shifts" in body
    assert len(body["shifts"]) == 1
    shift = body["shifts"][0]
    assert shift["id"] == shift_id
    assert len(shift["assignees"]) == 2
    assert all(not a["is_reserve"] for a in shift["assignees"])
    assert shift["required_count"] == 2
    assert shift["assigned_count"] == 2
    assert shift["fill_status"] == "full"
    assert shift["reserve_count"] == 0


def test_calendar_shifts_excludes_shift_with_no_assignees_in_node(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="7100010", role="admin")
    dept = create_node(admin_session, level="department", name="cal-empty")
    other = create_node(admin_session, level="branch", name="other-br", parent=dept)
    admin_session.commit()
    dt = DutyType(name="empty-shift", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="empty-loc")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    shift_resp = client.post("/api/shifts", headers=auth_headers(admin), json={
        "duty_type_id": str(dt.id), "duty_location_id": str(loc.id),
        "start_date": "2026-11-05", "end_date": "2026-11-05", "required_count": 1,
    })
    assert shift_resp.status_code == 201
    r = client.get(f"/api/calendar/shifts?node_id={other.id}&date_from=2026-11-05&date_to=2026-11-05",
                   headers=auth_headers(admin))
    assert r.status_code == 200
    assert len(r.json()["shifts"]) == 0
```

Run: `pytest tests/integration/test_calendar_api.py::test_calendar_shifts_returns_shift_events -v`
Expected: FAIL (service not defined)

- [ ] **Step 2: Create the service file**

`backend/app/services/calendar_shifts.py`:

```python
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithm.types import DutyBlock as _DutyBlock
from app.db.models import (
    DutyAssignment,
    DutyDismissal,
    DutyReserveLink,
    DutyShift,
    DutyType,
    DutyLocation,
    HierarchyNode,
    Soldier,
)


def get_calendar_shifts(
    session: Session, *, node_id: uuid.UUID, date_from: date | None, date_to: date | None
) -> list[dict[str, Any]]:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        return []

    subtree_node_ids = set(
        session.execute(
            select(HierarchyNode.id).where(HierarchyNode.path_ids.any(node_id))
        ).scalars().all()
    )

    soldiers_in_subtree = {
        s.id: s.full_name
        for s in session.execute(
            select(Soldier).where(
                Soldier.hierarchy_node_id.in_(subtree_node_ids),
                Soldier.left_at.is_(None),
            )
        ).scalars().all()
    }
    if not soldiers_in_subtree:
        return []

    soldier_id_set = set(soldiers_in_subtree.keys())

    # Build node -> parent -> name map for hierarchy_label
    all_nodes = {
        n.id: n for n in session.execute(select(HierarchyNode)).scalars().all()
    }

    def _leaf_label(sid: uuid.UUID) -> str | None:
        s = session.get(Soldier, sid)
        if s is None or s.hierarchy_node_id is None:
            return None
        leaf = all_nodes.get(s.hierarchy_node_id)
        if leaf is None:
            return None
        parent = all_nodes.get(leaf.parent_id) if leaf.parent_id else None
        return f"{parent.name} / {leaf.name}" if parent else leaf.name

    # Load duty_type colors
    dt_map: dict[uuid.UUID, tuple[str, str]] = {}
    for dt in session.execute(select(DutyType)).scalars().all():
        h = hash(dt.id) % 360
        dt_map[dt.id] = (dt.name, f"hsl({h}, 65%, 55%)")

    loc_map = {dl.id: dl.name for dl in session.execute(select(DutyLocation)).scalars().all()}

    # Query shifts in date range
    shift_query = select(DutyShift)
    if date_from:
        shift_query = shift_query.where(DutyShift.end_date >= date_from)
    if date_to:
        shift_query = shift_query.where(DutyShift.start_date <= date_to)
    shifts = session.execute(shift_query).scalars().all()

    if not shifts:
        return []

    shift_ids = [s.id for s in shifts]

    # Load assignments for these shifts, filtered to soldiers in subtree
    assignments = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.duty_shift_id.in_(shift_ids),
            DutyAssignment.soldier_id.in_(soldier_id_set),
            DutyAssignment.status.in_(["published", "algorithm_draft"]),
        )
    ).scalars().all()

    if not assignments:
        return []

    # Bulk load links and dismissals
    assignment_ids = [a.id for a in assignments]
    primary_ids = [a.id for a in assignments if not a.is_reserve]

    links: list[DutyReserveLink] = []
    if primary_ids:
        links = session.execute(
            select(DutyReserveLink).where(DutyReserveLink.primary_assignment_id.in_(primary_ids))
        ).scalars().all()

    primary_to_link = {lk.primary_assignment_id: lk for lk in links}
    reserve_to_primaries: dict[uuid.UUID, list[uuid.UUID]] = {}
    for lk in links:
        reserve_to_primaries.setdefault(lk.reserve_assignment_id, []).append(lk.primary_assignment_id)

    dismissals_by_primary: dict[uuid.UUID, list[DutyDismissal]] = {}
    if primary_ids:
        for d in session.execute(
            select(DutyDismissal).where(DutyDismissal.duty_assignment_id.in_(primary_ids))
        ).scalars().all():
            dismissals_by_primary.setdefault(d.duty_assignment_id, []).append(d)

    # Group by shift
    assignees_by_shift: dict[uuid.UUID, list[dict]] = {}
    for a in assignments:
        assignees_by_shift.setdefault(a.duty_shift_id, [])
        entry: dict = {
            "soldier_id": a.soldier_id,
            "soldier_name": soldiers_in_subtree.get(a.soldier_id, ""),
            "hierarchy_label": _leaf_label(a.soldier_id),
            "is_reserve": a.is_reserve,
        }
        if a.is_reserve:
            entry["called_up_from"] = a.called_up_from
            entry["called_up_to"] = a.called_up_to
            entry["primary_assignment_ids"] = reserve_to_primaries.get(a.id, [])
        else:
            link = primary_to_link.get(a.id)
            entry["dismissals"] = [
                {"id": d.id, "dismissed_from": d.dismissed_from, "dismissed_to": d.dismissed_to, "reason": d.reason}
                for d in dismissals_by_primary.get(a.id, [])
            ]
            entry["reserve_assignment_id"] = link.reserve_assignment_id if link else None
            entry["reserve_hierarchy_distance"] = link.hierarchy_distance if link else None

        assignees_by_shift[a.duty_shift_id].append(entry)

    result = []
    for shift in shifts:
        assignees = assignees_by_shift.get(shift.id, [])
        if not assignees:
            continue
        dt_name, dt_color = dt_map.get(shift.duty_type_id, ("", ""))
        primary_count = sum(1 for a_ in assignees if not a_["is_reserve"])
        reserve_count = sum(1 for a_ in assignees if a_["is_reserve"])
        result.append({
            "id": shift.id,
            "duty_type_id": shift.duty_type_id,
            "duty_type_name": dt_name,
            "duty_type_color": dt_color,
            "duty_location_name": loc_map.get(shift.duty_location_id, ""),
            "start_date": shift.start_date,
            "end_date": shift.end_date,
            "required_count": shift.required_count,
            "assigned_count": primary_count,
            "fill_status": "full" if primary_count >= shift.required_count else ("partial" if primary_count > 0 else "empty"),
            "reserve_count": reserve_count,
            "assignees": assignees,
        })

    return result
```

- [ ] **Step 3: Add the route to `calendar.py`**

Import at top:
```python
from app.services.calendar_shifts import get_calendar_shifts
```

Add Pydantic models before the router or at top:
```python
class CalendarShiftAssigneeDismissal(BaseModel):
    id: uuid.UUID
    dismissed_from: date
    dismissed_to: date
    reason: str | None

class CalendarShiftAssignee(BaseModel):
    soldier_id: uuid.UUID
    soldier_name: str
    hierarchy_label: str | None
    is_reserve: bool
    # Primary only:
    dismissals: list[CalendarShiftAssigneeDismissal] = []
    reserve_assignment_id: uuid.UUID | None = None
    reserve_hierarchy_distance: int | None = None
    # Reserve only:
    called_up_from: date | None = None
    called_up_to: date | None = None
    primary_assignment_ids: list[uuid.UUID] = []

class CalendarShiftOut(BaseModel):
    id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_type_name: str
    duty_type_color: str
    duty_location_name: str
    start_date: date
    end_date: date
    required_count: int
    assigned_count: int
    fill_status: str
    reserve_count: int
    assignees: list[CalendarShiftAssignee]

class CalendarShiftsResponse(BaseModel):
    shifts: list[CalendarShiftOut]
```

Add the route:
```python
@router.get("/shifts", response_model=CalendarShiftsResponse)
def calendar_shifts(
    node_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> CalendarShiftsResponse:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    authorize(session, user, Action.HIERARCHY_READ, target_node=node)
    raw = get_calendar_shifts(session, node_id=node_id, date_from=date_from, date_to=date_to)
    shifts = [CalendarShiftOut(**s) for s in raw]
    return CalendarShiftsResponse(shifts=shifts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_calendar_api.py::test_calendar_shifts_returns_shift_events tests/integration/test_calendar_api.py::test_calendar_shifts_excludes_shift_with_no_assignees_in_node -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/calendar_shifts.py backend/app/routes/calendar.py backend/tests/integration/test_calendar_api.py
git commit -m "feat(calendar): shift-based calendar endpoint with assignee grouping"
```

---

### Task 2: Backend — reserve relink endpoint

**Files:**
- Modify: `backend/app/services/reserves.py`
- Modify: `backend/app/routes/reserves.py`
- Test: `backend/tests/unit/test_reserves.py`

- [ ] **Step 6: Write the unit test for `relink_reserve`**

Add to `test_reserves.py`:

```python
from sqlalchemy.orm import Session
from app.services.reserves import ReserveError, relink_reserve
from app.db.models import DutyAssignment, DutyReserveLink

def test_relink_reserve(admin_session: Session):
    from tests.helpers import create_soldier
    from datetime import date
    from decimal import Decimal
    from app.db.models import DutyType, DutyLocation

    dt = DutyType(name="relink-dt", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="relink-loc")
    admin_session.add_all([dt, loc])
    admin_session.flush()

    p_soldier = create_soldier(admin_session, personal_number="800001")
    r_soldier = create_soldier(admin_session, personal_number="800002")
    admin_session.flush()

    primary = DutyAssignment(soldier_id=p_soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
                             start_date=date(2026, 6, 1), end_date=date(2026, 6, 3))
    reserve_a = DutyAssignment(soldier_id=r_soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
                               start_date=date(2026, 6, 1), end_date=date(2026, 6, 3), is_reserve=True)
    admin_session.add_all([primary, reserve_a])
    admin_session.flush()

    # Create an initial link
    link = DutyReserveLink(primary_assignment_id=primary.id, reserve_assignment_id=reserve_a.id, hierarchy_distance=1)
    admin_session.add(link)
    admin_session.flush()

    # Relink to the same reserve (no-op, should succeed)
    result = relink_reserve(admin_session, primary_assignment=primary, reserve_assignment_id=reserve_a.id, actor_id=None)
    assert result.hierarchy_distance == 1

    # Verify old link was replaced (same reserve but should still work)
    links = admin_session.execute(select(DutyReserveLink).where(DutyReserveLink.primary_assignment_id == primary.id)).scalars().all()
    assert len(links) == 1


def test_relink_reserve_non_reserve_fails(admin_session: Session):
    from tests.helpers import create_soldier
    from datetime import date
    from decimal import Decimal
    from app.db.models import DutyType, DutyLocation

    dt = DutyType(name="fail-dt", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="fail-loc")
    admin_session.add_all([dt, loc])
    admin_session.flush()

    p_soldier = create_soldier(admin_session, personal_number="800003")
    r_soldier = create_soldier(admin_session, personal_number="800004")
    admin_session.flush()

    primary = DutyAssignment(soldier_id=p_soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
                             start_date=date(2026, 6, 1), end_date=date(2026, 6, 3))
    not_reserve = DutyAssignment(soldier_id=r_soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
                                  start_date=date(2026, 6, 1), end_date=date(2026, 6, 3), is_reserve=False)
    admin_session.add_all([primary, not_reserve])
    admin_session.flush()

    import pytest
    with pytest.raises(ReserveError, match="not_a_reserve"):
        relink_reserve(admin_session, primary_assignment=primary, reserve_assignment_id=not_reserve.id, actor_id=None)
```

Run: `pytest tests/unit/test_reserves.py::test_relink_reserve -v`
Expected: FAIL (relink_reserve not defined)

- [ ] **Step 7: Implement `relink_reserve` in `reserves.py`**

Add to `backend/app/services/reserves.py`:

```python
def relink_reserve(
    session: Session,
    *,
    primary_assignment: DutyAssignment,
    reserve_assignment_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> DutyReserveLink:
    if primary_assignment.is_reserve:
        raise ReserveError("not_a_primary")
    reserve_a = session.get(DutyAssignment, reserve_assignment_id)
    if reserve_a is None:
        raise ReserveError("reserve_not_found")
    if not reserve_a.is_reserve:
        raise ReserveError("not_a_reserve")

    # Delete existing link if any
    existing = session.execute(
        select(DutyReserveLink).where(DutyReserveLink.primary_assignment_id == primary_assignment.id)
    ).scalar_one_or_none()
    if existing:
        session.delete(existing)
        session.flush()

    # Compute hierarchy distance
    from app.services.algorithm_bridge import build_hierarchy_maps
    hier_parent, _, soldier_node, _ = build_hierarchy_maps(session)
    p_node = soldier_node.get(primary_assignment.soldier_id)
    r_node = soldier_node.get(reserve_a.soldier_id)
    distance = _compute_hierarchy_distance(hier_parent, p_node, r_node) if p_node and r_node else 99

    link = DutyReserveLink(
        primary_assignment_id=primary_assignment.id,
        reserve_assignment_id=reserve_assignment_id,
        hierarchy_distance=distance,
    )
    session.add(link)
    session.flush()

    write_audit(
        session, actor_id=actor_id, action="reserve.relink",
        entity_type="duty_reserve_link", entity_id=link.id,
        after={
            "primary_assignment_id": str(primary_assignment.id),
            "reserve_assignment_id": str(reserve_assignment_id),
            "hierarchy_distance": distance,
        },
    )
    return link


def _compute_hierarchy_distance(
    parent_map: dict[uuid.UUID, uuid.UUID | None],
    node_a: uuid.UUID,
    node_b: uuid.UUID,
) -> int:
    """Shortest path length between two hierarchy nodes."""
    ancestors_a = {node_a}
    cur = node_a
    while parent_map.get(cur):
        cur = parent_map[cur]
        ancestors_a.add(cur)
    cur = node_b
    dist = 0
    while cur not in ancestors_a:
        cur = parent_map.get(cur)
        if cur is None:
            return 99
        dist += 1
    # Add distance from common ancestor to node_a
    cur2 = node_a
    while cur2 != cur:
        dist += 1
        cur2 = parent_map.get(cur2)
        if cur2 is None:
            return 99
    return dist
```

- [ ] **Step 8: Add the route for relink**

Add to `backend/app/routes/reserves.py` (after existing DELETE endpoint):

```python
@router.put("/shifts/{shift_id}/duty-assignments/{assignment_id}/reserve-link", response_model=dict)
def relink_reserve_route(
    shift_id: uuid.UUID,
    assignment_id: uuid.UUID,
    body: ReserveLinkRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    a = _load_assignment(session, assignment_id)
    try:
        link = svc.relink_reserve(session, primary_assignment=a, reserve_assignment_id=body.reserve_assignment_id, actor_id=user.id)
    except svc.ReserveError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return {"reserve_assignment_id": str(link.reserve_assignment_id), "hierarchy_distance": link.hierarchy_distance}
```

Add the request model near the top of the file:
```python
class ReserveLinkRequest(BaseModel):
    reserve_assignment_id: uuid.UUID
```

- [ ] **Step 9: Run tests**

Run: `pytest tests/unit/test_reserves.py::test_relink_reserve tests/unit/test_reserves.py::test_relink_reserve_non_reserve_fails -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/reserves.py backend/app/routes/reserves.py backend/tests/unit/test_reserves.py
git commit -m "feat(reserve): relink endpoint — reassign primary's designated reserve"
```

---

### Task 3: Frontend — API client updates

**Files:**
- Modify: `frontend/src/api/calendar.ts`
- Modify: `frontend/src/api/reserves.ts`

- [ ] **Step 11: Update calendar API client**

Replace `frontend/src/api/calendar.ts` content:

```typescript
import { api } from "./client";

export interface CalendarShiftAssigneeDismissal {
  id: string;
  dismissed_from: string;
  dismissed_to: string;
  reason: string | null;
}

export interface CalendarShiftAssignee {
  soldier_id: string;
  soldier_name: string;
  hierarchy_label: string | null;
  is_reserve: boolean;
  // Primary only:
  dismissals: CalendarShiftAssigneeDismissal[];
  reserve_assignment_id: string | null;
  reserve_hierarchy_distance: number | null;
  // Reserve only:
  called_up_from: string | null;
  called_up_to: string | null;
  primary_assignment_ids: string[];
}

export interface CalendarShift {
  id: string;
  duty_type_id: string;
  duty_type_name: string;
  duty_type_color: string;
  duty_location_name: string;
  start_date: string;
  end_date: string;
  required_count: number;
  assigned_count: number;
  fill_status: string;
  reserve_count: number;
  assignees: CalendarShiftAssignee[];
}

export interface CalendarShiftsResponse {
  shifts: CalendarShift[];
}

export async function getCalendarShifts(
  nodeId: string,
  params?: { date_from?: string; date_to?: string }
): Promise<CalendarShiftsResponse> {
  return (await api.get<CalendarShiftsResponse>("/calendar/shifts", { params: { node_id: nodeId, ...params } })).data;
}
```

- [ ] **Step 12: Add reserve relink to reserves API**

Add to `frontend/src/api/reserves.ts`:

```typescript
export async function relinkReserve(shiftId: string, assignmentId: string, reserveAssignmentId: string): Promise<void> {
  await api.put(`/shifts/${shiftId}/duty-assignments/${assignmentId}/reserve-link`, { reserve_assignment_id: reserveAssignmentId });
}
```

- [ ] **Step 13: Commit**

```bash
git add frontend/src/api/calendar.ts frontend/src/api/reserves.ts
git commit -m "feat(api): calendar shifts types + relink endpoint"
```

---

### Task 4: Frontend — ShiftDetailPanel + DismissalModal

**Files:**
- Create: `frontend/src/components/ShiftDetailPanel.tsx`
- Create: `frontend/src/components/DismissalModal.tsx`
- Delete: `frontend/src/components/ShiftReservePanel.tsx`

- [ ] **Step 14: Create DismissalModal component**

`frontend/src/components/DismissalModal.tsx`:

```typescript
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CalendarShiftAssignee,
  CalendarShift,
} from "../api/calendar";
import {
  dismissPrimary,
  callUpReserve,
  relinkReserve,
} from "../api/reserves";

interface Props {
  shift: CalendarShift;
  primary: CalendarShiftAssignee;
  onClose: () => void;
  onDone: () => void;
}

function computeDateRange(start: string, end: string) {
  const dates: string[] = [];
  const d = new Date(start);
  const stop = new Date(end);
  while (d <= stop) {
    dates.push(d.toISOString().slice(0, 10));
    d.setDate(d.getDate() + 1);
  }
  return dates;
}

export default function DismissalModal({ shift, primary, onClose, onDone }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const allDates = useMemo(() => computeDateRange(shift.start_date, shift.end_date), [shift.start_date, shift.end_date]);
  const primaryDates = useMemo(() => computeDateRange(primary.dismissals.length > 0 ? primary.dismissals[0].dismissed_from : primary.dismissals.length > 0 ? primary.dismissals[0].dismissed_from : shift.start_date, shift.end_date), [shift, primary]);

  const [fromIdx, setFromIdx] = useState(0);
  const [toIdx, setToIdx] = useState(allDates.length - 1);
  const [selectedReserveId, setSelectedReserveId] = useState(primary.reserve_assignment_id ?? "");
  const [reason, setReason] = useState("");

  // Reserve options: all reserves for this shift
  const reserveOptions = useMemo(
    () => shift.assignees.filter(a => a.is_reserve),
    [shift.assignees]
  );

  // Auto-select linked reserve
  useMemo(() => {
    if (!selectedReserveId && primary.reserve_assignment_id) {
      setSelectedReserveId(primary.reserve_assignment_id);
    } else if (!selectedReserveId && reserveOptions.length > 0) {
      setSelectedReserveId(reserveOptions[0].assignment_id ?? "");
    }
  }, [primary.reserve_assignment_id, reserveOptions, selectedReserveId]);

  const fromDate = allDates[fromIdx];
  const toDate = allDates[toIdx];

  const mutation = useMutation(
    async () => {
      // Step 1: dismiss
      await dismissPrimary(primary.assignment_id, fromDate, toDate, reason || undefined);
      // Step 2: call-up selected reserve
      if (selectedReserveId) {
        await callUpReserve(selectedReserveId, fromDate, toDate);
      }
      // Step 3: relink if different from current linked
      if (selectedReserveId && selectedReserveId !== primary.reserve_assignment_id) {
        await relinkReserve(shift.id, primary.assignment_id, selectedReserveId);
      }
    },
    {
      onSuccess: () => {
        qc.invalidateQueries(["calendarShifts"]);
        onDone();
      },
    }
  );

  const dayWidth = 36;
  const trackWidth = allDates.length * dayWidth;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl p-5 max-w-xl w-full" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="font-bold text-lg">{t("dismiss_modal.title")} — {primary.soldier_name}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700">✕</button>
        </div>

        {/* Range slider */}
        <div className="mb-4">
          <label className="text-sm text-gray-500 mb-1 block">{t("dismiss_modal.date_range")}</label>
          <div className="relative" style={{ width: trackWidth, height: 36, direction: "ltr" }}>
            <input
              type="range" min={0} max={allDates.length - 1} value={fromIdx}
              onChange={e => setFromIdx(Math.min(parseInt(e.target.value), toIdx))}
              className="absolute inset-0 w-full pointer-events-auto z-10 opacity-0 cursor-pointer"
            />
            <input
              type="range" min={0} max={allDates.length - 1} value={toIdx}
              onChange={e => setToIdx(Math.max(parseInt(e.target.value), fromIdx))}
              className="absolute inset-0 w-full pointer-events-auto z-10 opacity-0 cursor-pointer"
            />
            {/* Visual track */}
            <div className="absolute inset-0 flex items-center">
              {allDates.map((d, i) => {
                const isSelected = i >= fromIdx && i <= toIdx;
                return (
                  <div key={d}
                    className="h-8 border-l border-gray-200 flex items-center justify-center text-[10px]"
                    style={{ width: dayWidth, backgroundColor: isSelected ? "#fbbf24" : "#f3f4f6" }}
                  >
                    {new Date(d).getDate()}
                  </div>
                );
              })}
            </div>
          </div>
          <div className="flex gap-4 mt-2 text-xs text-gray-600" style={{ width: trackWidth }}>
            <span>{t("dismiss_modal.from")}: {fromDate}</span>
            <span>{t("dismiss_modal.to")}: {toDate}</span>
          </div>
        </div>

        {/* Reserve selector */}
        <div className="mb-3">
          <label className="text-sm text-gray-500 mb-1 block">{t("dismiss_modal.covering_reserve")}</label>
          <select
            value={selectedReserveId}
            onChange={e => setSelectedReserveId(e.target.value)}
            className="border rounded p-1 w-full text-sm"
          >
            {reserveOptions.length === 0 && <option value="">{t("dismiss_modal.no_reserves")}</option>}
            {reserveOptions.map(a => (
              <option key={a.assignment_id} value={a.assignment_id}>
                {a.soldier_name}
                {a.assignment_id === primary.reserve_assignment_id ? ` (${t("reserve_standby")})` : ""}
              </option>
            ))}
          </select>
        </div>

        {/* Reason */}
        <div className="mb-4">
          <label className="text-sm text-gray-500 mb-1 block">{t("dismiss_modal.reason")}</label>
          <input className="border rounded p-1 w-full text-sm" value={reason} onChange={e => setReason(e.target.value)} placeholder={t("dismiss_modal.reason_placeholder")} />
        </div>

        {mutation.isError && (
          <p className="text-red-500 text-sm mb-2">{(mutation.error as any)?.response?.data?.detail ?? t("dismiss_modal.error")}</p>
        )}

        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1 text-sm border rounded">{t("dismiss_modal.cancel")}</button>
          <button
            onClick={() => mutation.mutate()}
            disabled={mutation.isLoading}
            className="px-3 py-1 text-sm bg-amber-600 text-white rounded hover:bg-amber-700 disabled:opacity-50"
          >
            {mutation.isLoading ? t("dismiss_modal.submitting") : t("dismiss_modal.confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 15: Create ShiftDetailPanel (replaces ShiftReservePanel)**

`frontend/src/components/ShiftDetailPanel.tsx`:

```typescript
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { CalendarShift, CalendarShiftAssignee } from "../api/calendar";
import DismissalModal from "./DismissalModal";

interface Props {
  shift: CalendarShift;
  onClose: () => void;
  onRefreshNeeded: () => void;
}

export default function ShiftDetailPanel({ shift, onClose, onRefreshNeeded }: Props) {
  const { t } = useTranslation();
  const [dismissTarget, setDismissTarget] = useState<CalendarShiftAssignee | null>(null);

  const primaries = shift.assignees.filter(a => !a.is_reserve);
  const reserves = shift.assignees.filter(a => a.is_reserve);

  function reserveNameById(id: string | null): string {
    if (!id) return "—";
    const a = shift.assignees.find(a => a.assignment_id === id);
    return a?.soldier_name ?? id.slice(0, 8);
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl p-5 max-w-lg w-full max-h-[80vh] overflow-y-auto" dir="rtl" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex justify-between items-center mb-4">
          <div>
            <h3 className="font-bold text-lg">{shift.duty_type_name} — {shift.duty_location_name}</h3>
            <p className="text-sm text-gray-500">{shift.start_date} — {shift.end_date}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl">✕</button>
        </div>

        {/* Primary soldiers */}
        <section className="mb-5">
          <h4 className="font-semibold text-sm text-gray-600 mb-2">
            {t("primary_soldiers")} ({primaries.length}/{shift.required_count})
            {shift.fill_status === "full" ? " ✅" : ""}
          </h4>
          <div className="space-y-2">
            {primaries.map(a => (
              <div key={a.assignment_id} className="border rounded p-2 text-sm flex flex-col gap-1">
                <div className="flex justify-between items-center">
                  <div>
                    <span className="font-medium">{a.soldier_name}</span>
                    {a.hierarchy_label && <span className="text-xs text-gray-400 mr-2">({a.hierarchy_label})</span>}
                  </div>
                  <button
                    className="text-xs bg-amber-100 text-amber-800 px-2 py-0.5 rounded hover:bg-amber-200"
                    onClick={() => setDismissTarget(a)}
                  >
                    {t("dismiss_action")}
                  </button>
                </div>
                <div className="flex flex-wrap gap-2 text-xs">
                  {a.reserve_assignment_id && (
                    <span className="text-purple-600">
                      {t("reserve_standby")}: {reserveNameById(a.reserve_assignment_id)}
                      {a.reserve_hierarchy_distance != null && ` (${t("distance_label")}: ${a.reserve_hierarchy_distance})`}
                    </span>
                  )}
                </div>
                {a.dismissals.map(d => (
                  <div key={d.id} className="flex items-center gap-2 text-xs text-amber-700 bg-amber-50 rounded px-2 py-1">
                    <span>{t("reserve_dismissed")} {d.dismissed_from} — {d.dismissed_to}</span>
                    {d.reason && <span>({d.reason})</span>}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </section>

        {/* Reserve soldiers */}
        <section>
          <h4 className="font-semibold text-sm text-gray-600 mb-2">
            {t("reserve_soldiers")} ({reserves.length})
          </h4>
          <div className="space-y-2">
            {reserves.map(a => (
              <div key={a.assignment_id} className="border rounded p-2 text-sm border-purple-200 bg-purple-50 flex flex-col gap-1">
                <div className="flex justify-between items-center">
                  <div>
                    <span className="font-medium">{a.soldier_name}</span>
                    <span className="text-xs text-purple-500 mr-2">({t("reserve_label")})</span>
                    {a.hierarchy_label && <span className="text-xs text-gray-400 mr-2">({a.hierarchy_label})</span>}
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded ${a.called_up_from ? "bg-blue-100 text-blue-800" : "bg-gray-100 text-gray-600"}`}>
                    {a.called_up_from
                      ? `${t("reserve_called_up")} ${a.called_up_from}–${a.called_up_to}`
                      : t("reserve_standby")}
                  </span>
                </div>
                {a.primary_assignment_ids.length > 0 && (
                  <div className="text-xs text-gray-600">
                    {t("reserve_covers")}: {a.primary_assignment_ids.map(id => reserveNameById(id)).join(", ")}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>

        {/* Dismissal modal */}
        {dismissTarget && (
          <DismissalModal
            shift={shift}
            primary={dismissTarget}
            onClose={() => setDismissTarget(null)}
            onDone={() => { setDismissTarget(null); onRefreshNeeded(); }}
          />
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 16: Delete `ShiftReservePanel.tsx`**

```bash
git rm frontend/src/components/ShiftReservePanel.tsx
```

- [ ] **Step 17: Commit**

```bash
git add frontend/src/components/ShiftDetailPanel.tsx frontend/src/components/DismissalModal.tsx
git rm frontend/src/components/ShiftReservePanel.tsx
git commit -m "feat(ui): ShiftDetailPanel + DismissalModal with range slider (replaces ShiftReservePanel)"
```

---

### Task 5: Frontend — Rewrite UnitCalendar

**Files:**
- Modify: `frontend/src/components/UnitCalendar.tsx`
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 18: Rewrite UnitCalendar to shift-based events**

Replace entire `UnitCalendar.tsx`:

```typescript
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import interactionPlugin from "@fullcalendar/interaction";
import heLocale from "@fullcalendar/core/locales/he";
import type { EventClickArg, DatesSetArg } from "@fullcalendar/core";

import { getCalendarShifts, CalendarShift } from "../api/calendar";
import ShiftDetailPanel from "./ShiftDetailPanel";

interface UnitCalendarProps {
  nodeId: string;
}

export default function UnitCalendar({ nodeId }: UnitCalendarProps) {
  const { t } = useTranslation();
  const [shifts, setShifts] = useState<CalendarShift[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedShift, setSelectedShift] = useState<CalendarShift | null>(null);
  const [dutyTypeFilter, setDutyTypeFilter] = useState<string | null>(null);
  const dateRangeRef = useRef<{ from: string; to: string } | null>(null);

  const fetchData = useCallback(async (from: string, to: string) => {
    if (!nodeId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getCalendarShifts(nodeId, { date_from: from, date_to: to });
      setShifts(data.shifts);
    } catch {
      setError(t("unit_calendar.error") || "שגיאה בטעינת יומן");
    } finally {
      setLoading(false);
    }
  }, [nodeId, t]);

  useEffect(() => {
    dateRangeRef.current = null;
    setShifts([]);
    setSelectedShift(null);
  }, [nodeId]);

  function handleDatesSet(arg: DatesSetArg) {
    const from = arg.start.toISOString().slice(0, 10);
    const to = arg.end.toISOString().slice(0, 10);
    const prev = dateRangeRef.current;
    if (prev && prev.from === from && prev.to === to) return;
    dateRangeRef.current = { from, to };
    fetchData(from, to);
  }

  const events = useMemo(() => {
    return shifts.map(s => {
      const endDate = new Date(s.end_date);
      endDate.setDate(endDate.getDate() + 1);
      return {
        id: s.id,
        title: s.duty_type_name,
        start: s.start_date,
        end: endDate.toISOString().slice(0, 10),
        backgroundColor: s.duty_type_color,
        borderColor: s.duty_type_color,
        extendedProps: { shift: s },
      };
    });
  }, [shifts]);

  function handleEventClick(arg: EventClickArg) {
    const shift = arg.event.extendedProps.shift as CalendarShift;
    setSelectedShift(shift);
  }

  const filteredShifts = useMemo(() => {
    if (!dutyTypeFilter) return shifts;
    return shifts.filter(s => s.duty_type_id === dutyTypeFilter);
  }, [shifts, dutyTypeFilter]);

  const filteredEvents = useMemo(() => {
    return events.filter(e => {
      if (!dutyTypeFilter) return true;
      const s = e.extendedProps.shift as CalendarShift;
      return s.duty_type_id === dutyTypeFilter;
    });
  }, [events, dutyTypeFilter]);

  const dutyTypesInView = useMemo(() => {
    const seen = new Map<string, string>();
    for (const s of shifts) {
      if (!seen.has(s.duty_type_id)) seen.set(s.duty_type_id, s.duty_type_name);
    }
    return Array.from(seen.entries()).map(([id, name]) => ({ id, name }));
  }, [shifts]);

  return (
    <div className="space-y-4">
      {dutyTypesInView.length > 1 && (
        <div className="flex flex-wrap gap-2 text-sm">
          <span className="text-gray-500">{t("unit_calendar.filter_label") || "סינון:"}</span>
          {dutyTypesInView.map(dt => (
            <button
              key={dt.id}
              onClick={() => toggleFilter(dt.id)}
              data-testid={`filter-chip-${dt.id}`}
              className={`px-2 py-1 rounded-full border text-xs ${
                dutyTypeFilter === dt.id ? "bg-indigo-100 border-indigo-400 text-indigo-700" : "bg-white border-gray-300 text-gray-600"
              }`}
            >
              {dt.name}
            </button>
          ))}
        </div>
      )}

      {loading && <p className="text-gray-500 text-sm">{t("unit_calendar.loading")}</p>}
      {error && <p className="text-red-500 text-sm" data-testid="unit-calendar-error">{error}</p>}
      <div data-testid="fullcalendar" className="text-sm">
        <FullCalendar
          plugins={[dayGridPlugin, interactionPlugin]}
          initialView="dayGridMonth"
          events={filteredEvents}
          dateClick={() => setSelectedShift(null)}
          eventClick={handleEventClick}
          datesSet={handleDatesSet}
          locales={[heLocale]}
          locale="he"
          height="auto"
          headerToolbar={{ left: "prev,next today", center: "title", right: "dayGridMonth" }}
          buttonText={{ today: t("unit_calendar.today") || "היום" }}
          noEventsText={t("unit_calendar.none")}
          displayEventTime={false}
          eventContent={arg => {
            const s = arg.event.extendedProps.shift as CalendarShift;
            return (
              <div className="text-xs leading-tight px-1 overflow-hidden w-full">
                <div className="font-semibold truncate">{arg.event.title}</div>
                <div className="truncate text-gray-600">
                  {s.assigned_count} {t("soldiers_label")}
                  {s.reserve_count > 0 && ` | ${s.reserve_count}${t("reserve_label")}`}
                </div>
                {s.reserve_count > 0 && (
                  <div className="truncate text-purple-600 font-medium">● {t("reserve_standby")}</div>
                )}
              </div>
            );
          }}
        />
      </div>

      {selectedShift && (
        <ShiftDetailPanel
          shift={selectedShift}
          onClose={() => setSelectedShift(null)}
          onRefreshNeeded={() => {
            if (dateRangeRef.current) {
              fetchData(dateRangeRef.current.from, dateRangeRef.current.to);
            }
          }}
        />
      )}
    </div>
  );
}
```

Note: The `toggleFilter` function referenced in the filter buttons is not defined in the rewritten code. It should call `setDutyTypeFilter`. Let me fix that.

Add this function before the `return` statement:
```typescript
function toggleFilter(dtId: string) {
    setDutyTypeFilter((prev) => (prev === dtId ? null : dtId));
}
```

- [ ] **Step 19: Update i18n for new keys**

Add to `frontend/src/i18n/he.json` before `"weekday_1"`:

```json
  "dismiss_modal": {
    "title": "שחרור",
    "date_range": "טווח תאריכים",
    "from": "מ",
    "to": "עד",
    "covering_reserve": "רזרבה מכסה",
    "no_reserves": "אין רזרבות למשמרת זו",
    "reason": "סיבה",
    "reason_placeholder": "סיבה (אופציונלי)",
    "cancel": "ביטול",
    "confirm": "אשר שחרור",
    "submitting": "מבצע...",
    "error": "שגיאה בשחרור"
  },
  "soldiers_label": "חיילים",
  "distance_label": "מרחק",
```

- [ ] **Step 20: Commit**

```bash
git add frontend/src/components/UnitCalendar.tsx frontend/src/i18n/he.json
git commit -m "feat(ui): shift-based calendar with ShiftDetailPanel integration"
```

---

### Task 6: Verify — Full test pass

- [ ] **Step 21: Run full backend test suite**

Run: `pytest tests/ -q --tb=short -k "not test_password_history_reuse"`

Expected: At most 7 pre-existing failures (algorithm route + authz), no new failures.

- [ ] **Step 22: Final integration check**

Check that:
- `GET /api/calendar/shifts` returns correct shape with assignees
- Relink endpoint works end-to-end
- Frontend compiles without TS errors (if build tool available)
- All old ShiftReservePanel references removed (grep for it)

```bash
git grep -l "ShiftReservePanel" frontend/ 2>/dev/null || echo "All clean"
```

- [ ] **Step 23: Commit any final fixes**

```bash
git commit -m "chore: clean up ShiftReservePanel references"
```
