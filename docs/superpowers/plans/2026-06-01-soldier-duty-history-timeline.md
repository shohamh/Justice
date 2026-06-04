# Soldier Duty History Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "duty history" tab to the soldier modal showing a unified, filterable, timeline view of all events for a soldier (assignments, cancellations, reserve call-ups, dismissals, exemption requests, personal constraints).

**Architecture:** New aggregated query service (`backend/app/services/duty_history.py`) pulled by a single new endpoint (`GET /soldiers/{soldier_id}/duty-history`). Frontend has a new `DutyHistoryPanel` component added as a fifth tab in `UnifiedSoldierModal`. No DB migrations — all data already exists.

**Tech Stack:** FastAPI + SQLAlchemy (backend), React + TypeScript + i18next (frontend), existing auth/authz patterns.

**Feature branch:** `feature/soldier-duty-history` (create from master before starting)

---

### Task 0: Create feature branch

**Files:** (none)

- [ ] **Step 1: Create and checkout the feature branch**

```bash
git checkout -b feature/soldier-duty-history
```

Expected: `Switched to a new branch 'feature/soldier-duty-history'`

---

### Task 1: Backend service — duty history aggregation

**Files:**
- Create: `backend/app/services/duty_history.py`

**Context:**
- Models live in `backend/app/db/models.py`
- `DutyAssignment`: `id`, `soldier_id`, `duty_type_id`, `duty_location_id`, `start_date`, `end_date`, `status` (published/cancelled), `called_up_from`, `called_up_to`, `created_at`
- `DutyDismissal`: `id`, `duty_assignment_id`, `dismissed_from`, `dismissed_to`, `reason`, `created_at`
- `ExemptionRequest`: `id`, `soldier_id`, `exemption_type_id`, `start_date`, `end_date`, `reason`, `status`, `decision_note`, `created_at`
- `PersonalConstraint`: `id`, `soldier_id`, `start_date`, `end_date`, `reason`, `status`, `decision_note`, `created_at`
- `DutyType`: `id`, `name`; `DutyLocation`: `id`, `name`; `ExemptionType`: `id`, `name`

- [ ] **Step 1: Create the service file**

```python
# backend/app/services/duty_history.py
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyDismissal,
    DutyLocation,
    DutyType,
    ExemptionRequest,
    ExemptionType,
    PersonalConstraint,
)


@dataclass
class TimelineEvent:
    id: uuid.UUID
    event_type: str
    date: str
    end_date: str | None
    title: str
    description: str | None
    status: str | None
    metadata: dict = field(default_factory=dict)
    created_at: str = ""


def _isodate(d: date | None) -> str | None:
    return d.isoformat() if d else None


def get_duty_history(session: Session, soldier_id: uuid.UUID) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []

    # --- DutyAssignment events (assignment & cancellation & call_up) ---
    assignments = list(
        session.execute(
            select(DutyAssignment).where(DutyAssignment.soldier_id == soldier_id)
        ).scalars().all()
    )

    duty_type_cache: dict[uuid.UUID, str] = {}
    location_cache: dict[uuid.UUID, str] = {}

    def _duty_type_name(dt_id: uuid.UUID) -> str:
        if dt_id not in duty_type_cache:
            dt = session.get(DutyType, dt_id)
            duty_type_cache[dt_id] = dt.name if dt else str(dt_id)
        return duty_type_cache[dt_id]

    def _location_name(loc_id: uuid.UUID) -> str:
        if loc_id not in location_cache:
            loc = session.get(DutyLocation, loc_id)
            location_cache[loc_id] = loc.name if loc else str(loc_id)
        return location_cache[loc_id]

    for a in assignments:
        dt_name = _duty_type_name(a.duty_type_id)
        loc_name = _location_name(a.duty_location_id)

        # call_up event — if this assignment has called_up_from set
        if a.called_up_from is not None:
            events.append(
                TimelineEvent(
                    id=a.id,
                    event_type="call_up",
                    date=a.called_up_from.isoformat(),
                    end_date=_isodate(a.called_up_to),
                    title=f"הוקפץ לרזרבה: {dt_name}",
                    description=a.notes,
                    status=None,
                    metadata={
                        "duty_type_name": dt_name,
                        "location_name": loc_name,
                        "duty_assignment_id": str(a.id),
                    },
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
                    },
                    created_at=a.created_at.isoformat(),
                )
            )
        else:
            events.append(
                TimelineEvent(
                    id=a.id,
                    event_type="assignment",
                    date=a.start_date.isoformat(),
                    end_date=_isodate(a.end_date),
                    title=f"{dt_name} ב{loc_name}",
                    description=a.notes,
                    status=a.status,
                    metadata={
                        "duty_type_name": dt_name,
                        "location_name": loc_name,
                        "duty_assignment_id": str(a.id),
                    },
                    created_at=a.created_at.isoformat(),
                )
            )

        # dismissal events linked to this assignment
        dismissals = list(
            session.execute(
                select(DutyDismissal).where(DutyDismissal.duty_assignment_id == a.id)
            ).scalars().all()
        )
        for d in dismissals:
            events.append(
                TimelineEvent(
                    id=d.id,
                    event_type="dismissal",
                    date=d.dismissed_from.isoformat(),
                    end_date=_isodate(d.dismissed_to),
                    title=f"שוחרר מתורנות {dt_name}",
                    description=d.reason,
                    status=None,
                    metadata={
                        "duty_type_name": dt_name,
                        "location_name": loc_name,
                        "duty_assignment_id": str(a.id),
                    },
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
                title="בקשה אישית",
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

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/duty_history.py
git commit -m "feat: duty history aggregation service"
```

---

### Task 2: Backend route — GET /soldiers/{soldier_id}/duty-history

**Files:**
- Modify: `backend/app/routes/soldiers.py`

**Context:** The existing soldiers router already has `_load(session, soldier_id)`, `_node_of(session, s)`, and uses `authorize(session, user, Action.SOLDIER_READ, target_node=...)`. The `require_password_changed` and `require_roles` deps are already in scope.

- [ ] **Step 1: Add the `TimelineEventOut` schema and new route to soldiers.py**

Open `backend/app/routes/soldiers.py`. After the existing imports block, add `TimelineEvent` import and the Pydantic schema. Then at the end of the file, add the new route.

Add to the imports (after `from app.services.soldiers import ...`):

```python
from app.services.duty_history import get_duty_history
```

Add the schema class after the existing schema classes (e.g., after `FieldUpdateOut`):

```python
class TimelineEventOut(BaseModel):
    id: uuid.UUID
    event_type: str
    date: str
    end_date: str | None
    title: str
    description: str | None
    status: str | None
    metadata: dict
```

Add the route at the end of the file:

```python
@router.get("/{soldier_id}/duty-history", response_model=list[TimelineEventOut])
def get_soldier_duty_history(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
):
    s = _load(session, soldier_id)
    if str(s.id) != str(user.id):
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    events = get_duty_history(session, soldier_id)
    return [
        TimelineEventOut(
            id=e.id,
            event_type=e.event_type,
            date=e.date,
            end_date=e.end_date,
            title=e.title,
            description=e.description,
            status=e.status,
            metadata=e.metadata,
        )
        for e in events
    ]
```

- [ ] **Step 2: Verify the backend starts without error**

```bash
cd backend && uv run uvicorn app.main:app --reload --port 8000
```

Expected: server starts, no import errors. Stop with Ctrl+C.

- [ ] **Step 3: Commit**

```bash
git add backend/app/routes/soldiers.py
git commit -m "feat: GET /soldiers/{id}/duty-history route"
```

---

### Task 3: Backend tests

**Files:**
- Create: `backend/app/services/tests/test_duty_history.py`

**Context:** Look at `backend/app/services/tests/test_shift_templates.py` for the test session setup pattern. The test DB session is obtained via fixtures.

- [ ] **Step 1: Write the service unit test**

```python
# backend/app/services/tests/test_duty_history.py
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyDismissal,
    DutyLocation,
    DutyType,
    ExemptionRequest,
    ExemptionType,
    HierarchyNode,
    PersonalConstraint,
    Soldier,
)
from app.services.duty_history import get_duty_history


@pytest.fixture()
def node(db_session: Session) -> HierarchyNode:
    n = HierarchyNode(name="Unit A", node_type="unit")
    db_session.add(n)
    db_session.flush()
    return n


@pytest.fixture()
def soldier(db_session: Session, node: HierarchyNode) -> Soldier:
    s = Soldier(
        personal_number="111",
        full_name="Test Soldier",
        role="soldier",
        hierarchy_node_id=node.id,
        password_hash="x",
    )
    db_session.add(s)
    db_session.flush()
    return s


@pytest.fixture()
def duty_type(db_session: Session) -> DutyType:
    dt = DutyType(name="שמירה", notes=None)
    db_session.add(dt)
    db_session.flush()
    return dt


@pytest.fixture()
def duty_location(db_session: Session) -> DutyLocation:
    loc = DutyLocation(name="מחנה 80", hierarchy_node_id=None)
    db_session.add(loc)
    db_session.flush()
    return loc


@pytest.fixture()
def exemption_type(db_session: Session) -> ExemptionType:
    et = ExemptionType(name="מחלה", exempts_from_all=True)
    db_session.add(et)
    db_session.flush()
    return et


def test_empty_history(db_session: Session, soldier: Soldier) -> None:
    events = get_duty_history(db_session, soldier.id)
    assert events == []


def test_assignment_appears(
    db_session: Session, soldier: Soldier, duty_type: DutyType, duty_location: DutyLocation
) -> None:
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=duty_location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 11),
        status="published",
    )
    db_session.add(a)
    db_session.flush()

    events = get_duty_history(db_session, soldier.id)
    assert len(events) == 1
    e = events[0]
    assert e.event_type == "assignment"
    assert e.date == "2026-06-10"
    assert "שמירה" in e.title
    assert "מחנה 80" in e.title
    assert e.status == "published"


def test_cancellation_appears(
    db_session: Session, soldier: Soldier, duty_type: DutyType, duty_location: DutyLocation
) -> None:
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=duty_location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 11),
        status="cancelled",
    )
    db_session.add(a)
    db_session.flush()

    events = get_duty_history(db_session, soldier.id)
    assert len(events) == 1
    assert events[0].event_type == "cancellation"
    assert events[0].status == "cancelled"
    assert "בוטלה" in events[0].title


def test_call_up_appears(
    db_session: Session, soldier: Soldier, duty_type: DutyType, duty_location: DutyLocation
) -> None:
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=duty_location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 11),
        status="published",
        called_up_from=date(2026, 6, 8),
        called_up_to=date(2026, 6, 9),
    )
    db_session.add(a)
    db_session.flush()

    events = get_duty_history(db_session, soldier.id)
    event_types = [e.event_type for e in events]
    assert "call_up" in event_types
    assert "assignment" in event_types
    call_up = next(e for e in events if e.event_type == "call_up")
    assert call_up.date == "2026-06-08"
    assert "הוקפץ" in call_up.title


def test_dismissal_appears(
    db_session: Session, soldier: Soldier, duty_type: DutyType, duty_location: DutyLocation
) -> None:
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=duty_location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 14),
        status="published",
    )
    db_session.add(a)
    db_session.flush()

    d = DutyDismissal(
        duty_assignment_id=a.id,
        dismissed_from=date(2026, 6, 12),
        dismissed_to=date(2026, 6, 13),
        reason="חופשה",
    )
    db_session.add(d)
    db_session.flush()

    events = get_duty_history(db_session, soldier.id)
    event_types = [e.event_type for e in events]
    assert "dismissal" in event_types
    dismissal = next(e for e in events if e.event_type == "dismissal")
    assert dismissal.date == "2026-06-12"
    assert "שוחרר" in dismissal.title
    assert dismissal.description == "חופשה"


def test_exemption_request_appears(
    db_session: Session, soldier: Soldier, exemption_type: ExemptionType
) -> None:
    er = ExemptionRequest(
        soldier_id=soldier.id,
        exemption_type_id=exemption_type.id,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 5),
        reason="מחלה",
        status="pending",
    )
    db_session.add(er)
    db_session.flush()

    events = get_duty_history(db_session, soldier.id)
    assert len(events) == 1
    e = events[0]
    assert e.event_type == "exemption_request"
    assert "מחלה" in e.title
    assert e.status == "pending"


def test_personal_constraint_appears(db_session: Session, soldier: Soldier) -> None:
    c = PersonalConstraint(
        soldier_id=soldier.id,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 3),
        reason="בר מצווה",
        status="pending",
    )
    db_session.add(c)
    db_session.flush()

    events = get_duty_history(db_session, soldier.id)
    assert len(events) == 1
    e = events[0]
    assert e.event_type == "personal_constraint"
    assert e.description == "בר מצווה"
    assert e.status == "pending"


def test_sorted_descending(
    db_session: Session, soldier: Soldier, duty_type: DutyType, duty_location: DutyLocation
) -> None:
    a1 = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=duty_location.id,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 2),
        status="published",
    )
    a2 = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=duty_location.id,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        status="published",
    )
    db_session.add_all([a1, a2])
    db_session.flush()

    events = get_duty_history(db_session, soldier.id)
    dates = [e.date for e in events]
    assert dates == sorted(dates, reverse=True)
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
cd backend && uv run pytest app/services/tests/test_duty_history.py -v
```

Expected: all tests PASS

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/tests/test_duty_history.py
git commit -m "test: duty history service unit tests"
```

---

### Task 4: Frontend API client

**Files:**
- Create: `frontend/src/api/dutyHistory.ts`

- [ ] **Step 1: Create the API client**

```typescript
// frontend/src/api/dutyHistory.ts
import { api } from "./client";

export interface TimelineEvent {
  id: string;
  event_type:
    | "assignment"
    | "cancellation"
    | "call_up"
    | "dismissal"
    | "exemption_request"
    | "personal_constraint";
  date: string;
  end_date: string | null;
  title: string;
  description: string | null;
  status: string | null;
  metadata: Record<string, string | null>;
}

export async function getSoldierDutyHistory(
  soldierId: string,
): Promise<TimelineEvent[]> {
  return (
    await api.get<TimelineEvent[]>(`/soldiers/${soldierId}/duty-history`)
  ).data;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/dutyHistory.ts
git commit -m "feat: duty history API client"
```

---

### Task 5: i18n keys

**Files:**
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add duty_history namespace to he.json**

Find the end of the JSON object and add a new `"duty_history"` key before the closing `}`. The exact location depends on the current file — add it after the last top-level key.

```json
"duty_history": {
  "title": "היסטוריית תורנויות",
  "filter_all": "הכל",
  "filter_assignments": "תורנויות",
  "filter_cancellations": "ביטולים",
  "filter_call_ups": "הקפצות",
  "filter_dismissals": "שחרורים",
  "filter_exemption_requests": "בקשות פטור",
  "filter_constraints": "בקשות אישיות",
  "empty": "אין אירועים להצגה",
  "event_assignment": "תורנות",
  "event_cancellation": "ביטול תורנות",
  "event_call_up": "הקפצת רזרבה",
  "event_dismissal": "שחרור מתורנות",
  "event_exemption_request": "בקשת פטור",
  "event_constraint": "בקשה אישית"
}
```

Also add a `"team"` key `"duty_history"` for the tab label (used by `t("team.duty_history")`):
- Find the `"team"` section in he.json and add: `"duty_history": "היסטוריית תורנויות"`

- [ ] **Step 2: Commit**

```bash
git add frontend/src/i18n/he.json
git commit -m "feat: i18n keys for duty history tab"
```

---

### Task 6: DutyHistoryPanel component

**Files:**
- Create: `frontend/src/components/DutyHistoryPanel.tsx`

**Context:** `canManage` in the modal is `isAdmin || isDutyManager || user?.role === "commander"`. Approve/reject for exemption requests uses `approveExemptionRequest`/`rejectExemptionRequest` from `frontend/src/api/exemptions.ts`. Approve/reject for constraints uses `approveConstraint`/`rejectConstraint` from `frontend/src/api/constraints.ts`.

- [ ] **Step 1: Create the component**

```tsx
// frontend/src/components/DutyHistoryPanel.tsx
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  TimelineEvent,
  getSoldierDutyHistory,
} from "../api/dutyHistory";
import {
  approveExemptionRequest,
  rejectExemptionRequest,
} from "../api/exemptions";
import { approveConstraint, rejectConstraint } from "../api/constraints";

type FilterType =
  | "all"
  | "assignment"
  | "cancellation"
  | "call_up"
  | "dismissal"
  | "exemption_request"
  | "personal_constraint";

const FILTER_KEYS: { type: FilterType; i18nKey: string }[] = [
  { type: "all", i18nKey: "duty_history.filter_all" },
  { type: "assignment", i18nKey: "duty_history.filter_assignments" },
  { type: "cancellation", i18nKey: "duty_history.filter_cancellations" },
  { type: "call_up", i18nKey: "duty_history.filter_call_ups" },
  { type: "dismissal", i18nKey: "duty_history.filter_dismissals" },
  {
    type: "exemption_request",
    i18nKey: "duty_history.filter_exemption_requests",
  },
  {
    type: "personal_constraint",
    i18nKey: "duty_history.filter_constraints",
  },
];

const TYPE_COLORS: Record<string, string> = {
  assignment: "border-indigo-500 bg-indigo-50",
  cancellation: "border-red-400 bg-red-50",
  call_up: "border-orange-400 bg-orange-50",
  dismissal: "border-yellow-400 bg-yellow-50",
  exemption_request: "border-blue-400 bg-blue-50",
  personal_constraint: "border-purple-400 bg-purple-50",
};

const DOT_COLORS: Record<string, string> = {
  assignment: "bg-indigo-500",
  cancellation: "bg-red-400",
  call_up: "bg-orange-400",
  dismissal: "bg-yellow-400",
  exemption_request: "bg-blue-400",
  personal_constraint: "bg-purple-400",
};

const STATUS_BADGE: Record<string, string> = {
  published: "bg-green-100 text-green-800",
  active: "bg-green-100 text-green-800",
  approved: "bg-green-100 text-green-800",
  pending: "bg-yellow-100 text-yellow-800",
  cancelled: "bg-red-100 text-red-800",
  rejected: "bg-red-100 text-red-800",
};

interface Props {
  soldierId: string;
  canManage: boolean;
  isActive: boolean;
}

export default function DutyHistoryPanel({
  soldierId,
  canManage,
  isActive,
}: Props) {
  const { t } = useTranslation();
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<FilterType>("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  async function load() {
    setLoading(true);
    try {
      setEvents(await getSoldierDutyHistory(soldierId));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (isActive) void load();
  }, [isActive, soldierId]);

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleApproveExemption(id: string) {
    await approveExemptionRequest(id);
    await load();
  }

  async function handleRejectExemption(id: string) {
    const note = prompt(t("approvals.decision_note"));
    if (note === null) return;
    await rejectExemptionRequest(id, note || "");
    await load();
  }

  async function handleApproveConstraint(id: string) {
    await approveConstraint(id);
    await load();
  }

  async function handleRejectConstraint(id: string) {
    const note = prompt(t("approvals.decision_note"));
    if (note === null) return;
    await rejectConstraint(id, note || "");
    await load();
  }

  const displayed =
    filter === "all" ? events : events.filter((e) => e.event_type === filter);

  if (loading) {
    return <p className="text-sm text-gray-400">{t("app.loading")}</p>;
  }

  return (
    <div>
      {/* Filter chips */}
      <div className="flex flex-wrap gap-1 mb-4">
        {FILTER_KEYS.map(({ type, i18nKey }) => (
          <button
            key={type}
            onClick={() => setFilter(type)}
            className={`text-xs px-2 py-1 rounded-full border ${
              filter === type
                ? "bg-indigo-600 text-white border-indigo-600"
                : "border-gray-300 text-gray-600 hover:border-indigo-400"
            }`}
            data-testid={`history-filter-${type}`}
          >
            {t(i18nKey)}
          </button>
        ))}
      </div>

      {/* Timeline */}
      {displayed.length === 0 ? (
        <p className="text-sm text-gray-500">{t("duty_history.empty")}</p>
      ) : (
        <div className="relative">
          {/* Vertical line */}
          <div className="absolute right-3 top-0 bottom-0 w-px bg-gray-200" />

          <div className="space-y-3">
            {displayed.map((e) => {
              const isExpanded = expanded.has(e.id);
              const colorClass =
                TYPE_COLORS[e.event_type] ?? "border-gray-300 bg-gray-50";
              const dotColor = DOT_COLORS[e.event_type] ?? "bg-gray-400";
              const badgeClass = e.status
                ? (STATUS_BADGE[e.status] ?? "bg-gray-100 text-gray-600")
                : null;

              return (
                <div
                  key={`${e.event_type}-${e.id}`}
                  className="flex items-start gap-3 pr-6"
                  data-testid={`history-event-${e.event_type}`}
                >
                  {/* Dot */}
                  <div
                    className={`absolute right-1 mt-2 w-4 h-4 rounded-full border-2 border-white ${dotColor}`}
                  />

                  {/* Card */}
                  <div
                    className={`flex-1 border-r-4 rounded p-3 text-sm cursor-pointer ${colorClass}`}
                    onClick={() => toggleExpand(e.id)}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="font-medium">{e.title}</p>
                        <p className="text-xs text-gray-500" dir="ltr">
                          {e.date}
                          {e.end_date && e.end_date !== e.date
                            ? ` → ${e.end_date}`
                            : ""}
                        </p>
                      </div>
                      {badgeClass && (
                        <span
                          className={`text-xs px-1.5 py-0.5 rounded whitespace-nowrap ${badgeClass}`}
                        >
                          {t(`my_requests.${e.status}`)}
                        </span>
                      )}
                    </div>

                    {isExpanded && (
                      <div className="mt-2 space-y-1">
                        {e.description && (
                          <p className="text-gray-600">{e.description}</p>
                        )}
                        {e.metadata.decision_note && (
                          <p className="text-gray-400 text-xs">
                            {t("approvals.decision_note")}:{" "}
                            {e.metadata.decision_note}
                          </p>
                        )}

                        {canManage && e.status === "pending" && (
                          <div className="flex gap-2 mt-2">
                            {e.event_type === "exemption_request" && (
                              <>
                                <button
                                  className="text-xs text-green-600 hover:underline"
                                  onClick={(ev) => {
                                    ev.stopPropagation();
                                    void handleApproveExemption(e.id);
                                  }}
                                  data-testid={`approve-exemption-${e.id}`}
                                >
                                  {t("approvals.approve")}
                                </button>
                                <button
                                  className="text-xs text-red-600 hover:underline"
                                  onClick={(ev) => {
                                    ev.stopPropagation();
                                    void handleRejectExemption(e.id);
                                  }}
                                  data-testid={`reject-exemption-${e.id}`}
                                >
                                  {t("approvals.reject")}
                                </button>
                              </>
                            )}
                            {e.event_type === "personal_constraint" && (
                              <>
                                <button
                                  className="text-xs text-green-600 hover:underline"
                                  onClick={(ev) => {
                                    ev.stopPropagation();
                                    void handleApproveConstraint(e.id);
                                  }}
                                  data-testid={`approve-constraint-hist-${e.id}`}
                                >
                                  {t("approvals.approve")}
                                </button>
                                <button
                                  className="text-xs text-red-600 hover:underline"
                                  onClick={(ev) => {
                                    ev.stopPropagation();
                                    void handleRejectConstraint(e.id);
                                  }}
                                  data-testid={`reject-constraint-hist-${e.id}`}
                                >
                                  {t("approvals.reject")}
                                </button>
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/DutyHistoryPanel.tsx
git commit -m "feat: DutyHistoryPanel component"
```

---

### Task 7: Wire up tab in UnifiedSoldierModal

**Files:**
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx`

**Context:** Current `TABS` is `["details", "profile", "exemptions", "constraints"]`. Tab labels come from `t("team.<tab_key>")` — so `"duty_history"` tab label is `t("team.duty_history")`.

- [ ] **Step 1: Add import and update TABS**

In `UnifiedSoldierModal.tsx`, add the import at the top:

```typescript
import DutyHistoryPanel from "./DutyHistoryPanel";
```

Change the TABS constant:

```typescript
const TABS = ["details", "profile", "exemptions", "constraints", "duty_history"] as const;
```

- [ ] **Step 2: Add the new tab panel**

After the closing `}` of the `{tab === "constraints" && (...)}` block, add:

```tsx
{tab === "duty_history" && (
  <DutyHistoryPanel
    soldierId={soldier.id}
    canManage={canManage}
    isActive={tab === "duty_history"}
  />
)}
```

- [ ] **Step 3: Build to check for TypeScript errors**

```bash
cd frontend && pnpm build 2>&1 | tail -20
```

Expected: build succeeds with no TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/UnifiedSoldierModal.tsx
git commit -m "feat: add duty_history tab to UnifiedSoldierModal"
```

---

### Task 8: Verify in browser

- [ ] **Step 1: Start dev servers**

In one terminal:
```bash
cd backend && uv run uvicorn app.main:app --reload --port 8000
```

In another:
```bash
cd frontend && pnpm dev
```

- [ ] **Step 2: Manual smoke test**

1. Log in as admin
2. Go to Team page, open a soldier modal
3. Verify "היסטוריית תורנויות" tab appears
4. Click it — verify timeline loads (or empty state if no data)
5. If there is data: click filter chips to confirm they work
6. Click a card to expand it and see description/details
7. If a pending exemption or constraint is shown: verify approve/reject buttons appear for admin

- [ ] **Step 3: Commit any UI fixes found during smoke test**

```bash
git add -p
git commit -m "fix: <describe what was fixed>"
```

---

### Task 9: Final cleanup and branch push

- [ ] **Step 1: Run backend tests one more time**

```bash
cd backend && uv run pytest app/services/tests/test_duty_history.py -v
```

Expected: all PASS

- [ ] **Step 2: Push feature branch**

```bash
git push -u origin feature/soldier-duty-history
```
