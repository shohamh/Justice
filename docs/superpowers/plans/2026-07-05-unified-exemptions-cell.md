# Unified Exemptions Cell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify the פטורים (exemptions) column rendering between the Transparency and Potential pages into one shared, clickable component backed by a new per-soldier exemption summary field on both endpoints, plus a new read-only exemption-instance detail endpoint/modal — all while preserving today's two distinct visibility-permission checks exactly.

**Architecture:** Both `/scoring/transparency` and `/potential` get a new additive `exemptions: list[ExemptionSummaryItem]` field (id, type name, category, dates only — no `reason`/`granted_by`), gated by each endpoint's own existing coarse visibility check, empty when that check fails (no count leak). A new `GET /soldiers/{soldier_id}/exemptions/{exemption_id}` endpoint independently re-authorizes (`Action.EXEMPTION_READ` + `can_see_private()` gating `reason`) and serves the richer instance data for a new shared frontend modal, reached via a new shared `ExemptionsCell` component used by both pages.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, pytest; React/TypeScript, react-i18next.

## Global Constraints

- `ExemptionSummaryItem` (bulk/table-level, both endpoints): `id`, `exemption_type_name`, `is_global`, `start_date`, `end_date` — **no** `reason`, **no** `granted_by`.
- Table-level visibility stays exactly as today: Transparency's per-soldier `in_scope` check (`backend/app/services/scoring.py:538-544`); Potential's per-request `can_view_exemptions` check (`backend/app/routes/potential.py:80-81`). When either fails, the `exemptions` array is **empty** — never a count-preserving list of placeholders.
- Detail-level data (`reason`, `granted_by_name`) is served **only** by the new `GET /soldiers/{soldier_id}/exemptions/{exemption_id}` endpoint, which re-authorizes independently via `Action.EXEMPTION_READ` (same as the existing `list_exemptions` endpoint) and gates `reason` specifically with `can_see_private()` — `granted_by_name` is shown whenever the base `EXEMPTION_READ` check passes, matching existing `ExemptionOut` precedent (`backend/app/routes/exemptions.py:37-46`).
- `is_medical`/`is_commander_exemption` get no additional redaction (confirmed display-only today) — none introduced.
- Existing fields (`exemptions_display`, `exemption_names`, `partial_exemption_names`) and Transparency's CSV `exportValue` are unchanged.
- `ExemptionTypeViewModal` is untouched and keeps its existing (unrelated) usage; the new `ExemptionInstanceModal` is a separate component.

---

### Task 1: Backend — `exemptions` field on Transparency

**Files:**
- Modify: `backend/app/services/scoring.py:537-576` (row-building loop)
- Modify: `backend/app/routes/scoring.py:21-43` (`TransparencyRow`, add `ExemptionSummaryItem`)
- Test: `backend/tests/integration/test_scoring_api.py`

**Interfaces:**
- Produces: `TransparencyRow.exemptions: list[ExemptionSummaryItem]` (Pydantic, in `backend/app/routes/scoring.py`), populated from `scoring.py`'s existing `soldier_exemptions`/`in_scope` per-row computation.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_scoring_api.py`:

```python
def test_transparency_exemptions_array_populated_in_scope(client: TestClient, admin_session: Session):
    from datetime import date

    from app.db.models import ExemptionType, SoldierExemption
    from tests.helpers import create_node

    node = create_node(admin_session, level="division", name="div-api-exarr")
    cmd = create_soldier(admin_session, personal_number="5600020", role="commander")
    node.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="5600021", hierarchy_node_id=node.id)
    et = ExemptionType(name="פטור-מערך1", is_global=True)
    admin_session.add(et)
    admin_session.flush()
    ex = SoldierExemption(
        soldier_id=target.id, exemption_type_id=et.id,
        start_date=date(2026, 1, 1), end_date=date(2026, 5, 1),
    )
    admin_session.add(ex)
    admin_session.commit()
    admin_session.refresh(ex)

    r = client.get("/api/scoring/transparency", headers=auth_headers(cmd))
    row = next(x for x in r.json()["rows"] if x["soldier_id"] == str(target.id))
    assert row["exemptions_visible"] is True
    assert len(row["exemptions"]) == 1
    item = row["exemptions"][0]
    assert item["id"] == str(ex.id)
    assert item["exemption_type_name"] == "פטור-מערך1"
    assert item["is_global"] is True
    assert item["start_date"] == "2026-01-01"
    assert item["end_date"] == "2026-05-01"


def test_transparency_exemptions_array_empty_when_redacted(client: TestClient, admin_session: Session):
    from datetime import date

    from app.db.models import ExemptionType, SoldierExemption
    from tests.helpers import create_node

    node = create_node(admin_session, level="division", name="div-api-exarr2")
    viewer = create_soldier(admin_session, personal_number="5600022", role="soldier")
    target = create_soldier(admin_session, personal_number="5600023", hierarchy_node_id=node.id)
    et = ExemptionType(name="פטור-מערך2", is_global=True)
    admin_session.add(et)
    admin_session.flush()
    admin_session.add(
        SoldierExemption(soldier_id=target.id, exemption_type_id=et.id, start_date=date.today())
    )
    admin_session.commit()

    r = client.get("/api/scoring/transparency", headers=auth_headers(viewer))
    row = next(x for x in r.json()["rows"] if x["soldier_id"] == str(target.id))
    assert row["exemptions_visible"] is False
    assert row["exemptions"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_scoring_api.py -k exemptions_array -v`
Expected: FAIL with `KeyError: 'exemptions'` (field doesn't exist on the response yet).

- [ ] **Step 3: Write minimal implementation**

In `backend/app/routes/scoring.py`, add a new schema right before `TransparencyRow` (around line 21):

```python
class ExemptionSummaryItem(BaseModel):
    id: uuid.UUID
    exemption_type_name: str
    is_global: bool
    start_date: date
    end_date: date | None
```

Add a field to `TransparencyRow` (after `exemptions_visible: bool = False` at line 40):

```python
    exemptions_visible: bool = False
    exemptions: list[ExemptionSummaryItem] = []
```

In `backend/app/services/scoring.py`, inside the row-building loop (around line 538-544), build the new list alongside the existing `exemptions_display` computation:

```python
        in_scope = node is not None and any(root in node.path_ids for root in roots)
        if in_scope:
            exemptions_display = ", ".join(
                _exemption_label(exemption, ex_type) for exemption, ex_type in soldier_exemptions
            )
            exemptions_summary = [
                {
                    "id": exemption.id,
                    "exemption_type_name": ex_type.name,
                    "is_global": ex_type.is_global,
                    "start_date": exemption.start_date,
                    "end_date": exemption.end_date,
                }
                for exemption, ex_type in soldier_exemptions
            ]
        else:
            exemptions_display = "חסוי"
            exemptions_summary = []
```

Then add `"exemptions": exemptions_summary,` to the `rows.append({...})` dict (right after the existing `"exemptions_visible": in_scope,` line, around line 568).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_scoring_api.py -v`
Expected: PASS (all tests, including the 2 new ones)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/scoring.py backend/app/routes/scoring.py backend/tests/integration/test_scoring_api.py
git commit -m "feat: add per-exemption summary array to transparency endpoint"
```

---

### Task 2: Backend — `exemptions` field on Potential

**Files:**
- Modify: `backend/app/services/potential.py:25-33, 156-187` (`SoldierPotentialDetail`, exemption computation)
- Modify: `backend/app/routes/potential.py:22-77` (`SoldierDetailOut`, `_out`)
- Test: `backend/tests/integration/test_potential_api.py` (new file — no existing tests cover this endpoint today)

**Interfaces:**
- Consumes: nothing from Task 1 (independent endpoint).
- Produces: `SoldierDetailOut.exemptions: list[ExemptionSummaryItemOut]` (same shape as Task 1's `ExemptionSummaryItem`, defined locally in `routes/potential.py` per this codebase's per-route-file schema convention).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_potential_api.py`:

```python
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import DutyType, ExemptionType, SoldierExemption
from tests.helpers import auth_headers, create_node, create_soldier


def test_potential_exemptions_array_populated_when_authorized(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="division", name="div-pot-1")
    cmd = create_soldier(admin_session, personal_number="5700001", role="commander")
    node.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="5700002", hierarchy_node_id=node.id)
    dt = DutyType(name="שמירה-pot1", score_per_day=Decimal("1.00"))
    et = ExemptionType(name="פטור-פוט1", is_global=True)
    admin_session.add_all([dt, et])
    admin_session.flush()
    ex = SoldierExemption(
        soldier_id=target.id, exemption_type_id=et.id,
        start_date=date(2026, 1, 1), end_date=None,
    )
    admin_session.add(ex)
    admin_session.commit()
    admin_session.refresh(ex)

    r = client.get(
        "/api/potential", params={"node_id": str(node.id)}, headers=auth_headers(cmd),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    row = next(s for s in body["soldiers"] if s["soldier_id"] == str(target.id))
    assert row["exemptions"] is not None
    assert len(row["exemptions"]) == 1
    item = row["exemptions"][0]
    assert item["id"] == str(ex.id)
    assert item["exemption_type_name"] == "פטור-פוט1"
    assert item["is_global"] is True
    assert item["end_date"] is None


def test_potential_exemptions_array_empty_when_not_authorized(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="division", name="div-pot-2")
    viewer = create_soldier(admin_session, personal_number="5700003", role="soldier")
    target = create_soldier(admin_session, personal_number="5700004", hierarchy_node_id=node.id)
    dt = DutyType(name="שמירה-pot2", score_per_day=Decimal("1.00"))
    et = ExemptionType(name="פטור-פוט2", is_global=True)
    admin_session.add_all([dt, et])
    admin_session.flush()
    admin_session.add(SoldierExemption(soldier_id=target.id, exemption_type_id=et.id, start_date=date(2026, 1, 1)))
    admin_session.commit()

    r = client.get(
        "/api/potential", params={"node_id": str(node.id)}, headers=auth_headers(viewer),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    row = next(s for s in body["soldiers"] if s["soldier_id"] == str(target.id))
    assert row["exemptions"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_potential_api.py -v`
Expected: FAIL with `KeyError: 'exemptions'`.

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/potential.py`, add a new dataclass right after the imports (around line 22, before `SoldierPotentialDetail`):

```python
@dataclass
class ExemptionSummary:
    id: uuid.UUID
    exemption_type_name: str
    is_global: bool
    start_date: date
    end_date: date | None
```

Add a field to `SoldierPotentialDetail` (after `partial_exemption_names`, around line 33):

```python
    partial_exemption_names: list[str] = field(default_factory=list)  # populated when counted is True but partially exempt
    exemptions: list[ExemptionSummary] = field(default_factory=list)
```

In `compute_potential` (around lines 164-187), build the matching `ExemptionSummary` list alongside each existing `names`/`partial_names` computation — replace the two `details.append(...)` calls:

```python
        if remaining:
            partial_names: list[str] = []
            partial_items: list[ExemptionSummary] = []
            if excluded & base_eligible:
                relevant = [
                    ex for ex in active_exemptions
                    if etid_to_dtids.get(ex.exemption_type_id, set()) & base_eligible
                ]
                partial_names = sorted({regular_types[ex.exemption_type_id].name for ex in relevant})
                partial_items = [
                    ExemptionSummary(
                        id=ex.id,
                        exemption_type_name=regular_types[ex.exemption_type_id].name,
                        is_global=regular_types[ex.exemption_type_id].is_global,
                        start_date=ex.start_date,
                        end_date=ex.end_date,
                    )
                    for ex in relevant
                ]
            details.append(SoldierPotentialDetail(
                s.id, s.full_name, True, rank=rank, partial_exemption_names=partial_names,
                exemptions=partial_items,
            ))
            raw_count += 1
        elif base_eligible:
            # would have been eligible, but active exemptions excluded every remaining duty type
            relevant = [
                ex for ex in active_exemptions
                if etid_to_dtids.get(ex.exemption_type_id, set()) & base_eligible
            ]
            names = sorted({regular_types[ex.exemption_type_id].name for ex in relevant})
            items = [
                ExemptionSummary(
                    id=ex.id,
                    exemption_type_name=regular_types[ex.exemption_type_id].name,
                    is_global=regular_types[ex.exemption_type_id].is_global,
                    start_date=ex.start_date,
                    end_date=ex.end_date,
                )
                for ex in relevant
            ]
            details.append(SoldierPotentialDetail(
                s.id, s.full_name, False, "exempted", names, rank=rank, exemptions=items,
            ))
```

In `backend/app/routes/potential.py`, add a schema right before `SoldierDetailOut` (around line 22):

```python
class ExemptionSummaryItemOut(BaseModel):
    id: uuid.UUID
    exemption_type_name: str
    is_global: bool
    start_date: date
    end_date: date | None
```

Add `date` to the route file's imports (it currently imports `from datetime import date` at line 5 — already present, no change needed there).

Add a field to `SoldierDetailOut` (after `partial_exemption_names`, around line 29):

```python
    partial_exemption_names: list[str] | None = None
    exemptions: list[ExemptionSummaryItemOut] | None = None
```

Update `_out()` (around lines 67-74) to populate it, gated by the same `can_view_exemptions` flag as the existing name fields:

```python
        soldiers=[
            SoldierDetailOut(
                soldier_id=s.soldier_id, full_name=s.full_name, counted=s.counted, reason=s.reason,
                exemption_names=(s.exemption_names or None) if can_view_exemptions else None,
                rank=s.rank,
                partial_exemption_names=(s.partial_exemption_names or None) if can_view_exemptions else None,
                exemptions=(
                    [
                        ExemptionSummaryItemOut(
                            id=e.id, exemption_type_name=e.exemption_type_name,
                            is_global=e.is_global, start_date=e.start_date, end_date=e.end_date,
                        )
                        for e in s.exemptions
                    ]
                    if can_view_exemptions else None
                ),
            )
            for s in r.soldiers
        ],
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_potential_api.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/potential.py backend/app/routes/potential.py backend/tests/integration/test_potential_api.py
git commit -m "feat: add per-exemption summary array to potential endpoint"
```

---

### Task 3: Backend — exemption detail endpoint

**Files:**
- Modify: `backend/app/routes/exemptions.py`
- Test: `backend/tests/integration/test_exemptions_api.py`

**Interfaces:**
- Consumes: nothing from Tasks 1-2.
- Produces: `GET /soldiers/{soldier_id}/exemptions/{exemption_id}` → `ExemptionDetailOut` (`id`, `exemption_type_name`, `is_global`, `start_date`, `end_date`, `reason`, `granted_by_name`). Used by Task 6 (frontend modal).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_exemptions_api.py`:

```python
def test_detail_endpoint_shows_reason_when_authorized(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d-detail1")
    b = create_node(admin_session, level="branch", name="b-detail1", parent=d)
    cmd = create_soldier(admin_session, personal_number="5200020", role="commander")
    b.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="5200021", hierarchy_node_id=b.id)
    et = _et(admin_session, "פטור-דטייל1")
    r = client.post(
        f"/api/soldiers/{target.id}/exemptions",
        headers=auth_headers(cmd),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01", "end_date": "2026-06-01", "reason": "בעיה רפואית"},
    )
    exemption_id = r.json()["id"]

    r2 = client.get(f"/api/soldiers/{target.id}/exemptions/{exemption_id}", headers=auth_headers(cmd))
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["exemption_type_name"] == "פטור-דטייל1"
    assert body["is_global"] is False
    assert body["start_date"] == "2026-01-01"
    assert body["end_date"] == "2026-06-01"
    assert body["reason"] == "בעיה רפואית"
    assert body["granted_by_name"] == cmd.full_name


def test_detail_endpoint_hides_reason_when_not_private(client: TestClient, admin_session: Session):
    """A plain admin (not also a commander/duty-manager) passes EXEMPTION_READ
    unconditionally (authz.can(): `if user.role == "admin": return True`), but
    can_see_private_node() deliberately does NOT grant admins a bypass — it
    requires is_commander or is_duty_manager. So a plain admin is exactly the
    "can read, cannot see private fields" case: reason must come back None."""
    node = create_node(admin_session, level="department", name="d-detail2")
    admin_grantor = create_soldier(admin_session, personal_number="5200022", role="admin")
    target = create_soldier(admin_session, personal_number="5200023", hierarchy_node_id=node.id)
    et = _et(admin_session, "פטור-דטייל2")
    r = client.post(
        f"/api/soldiers/{target.id}/exemptions",
        headers=auth_headers(admin_grantor),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01", "reason": "סודי"},
    )
    exemption_id = r.json()["id"]

    viewer_admin = create_soldier(admin_session, personal_number="5200024", role="admin")
    r2 = client.get(f"/api/soldiers/{target.id}/exemptions/{exemption_id}", headers=auth_headers(viewer_admin))
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["reason"] is None
    assert body["exemption_type_name"] == "פטור-דטייל2"  # non-private fields still shown


def test_detail_endpoint_404_for_mismatched_soldier(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200027", role="admin")
    s1 = create_soldier(admin_session, personal_number="5200028", role="soldier")
    s2 = create_soldier(admin_session, personal_number="5200029", role="soldier")
    et = _et(admin_session, "פטור-דטייל4")
    r = client.post(
        f"/api/soldiers/{s1.id}/exemptions",
        headers=auth_headers(admin),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01"},
    )
    exemption_id = r.json()["id"]
    r2 = client.get(f"/api/soldiers/{s2.id}/exemptions/{exemption_id}", headers=auth_headers(admin))
    assert r2.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_exemptions_api.py -k detail_endpoint -v`
Expected: FAIL with 404 (route doesn't exist yet) on all three.

- [ ] **Step 3: Write minimal implementation**

In `backend/app/routes/exemptions.py`, update the imports (line 12):

```python
from app.db.models import ExemptionType, HierarchyNode, Soldier, SoldierExemption
```

Add a new schema right after `ExemptionOut` (around line 27):

```python
class ExemptionDetailOut(BaseModel):
    id: uuid.UUID
    exemption_type_name: str
    is_global: bool
    start_date: date
    end_date: date | None
    reason: str | None
    granted_by_name: str | None
```

Add a new route right after `list_()` (around line 71, before the `grant()` route):

```python
@router.get("/{exemption_id}", response_model=ExemptionDetailOut)
def get_detail(
    soldier_id: uuid.UUID,
    exemption_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionDetailOut:
    s = _load_soldier(session, soldier_id)
    ex = session.get(SoldierExemption, exemption_id)
    if ex is None or ex.soldier_id != soldier_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if s.id != user.id:
        authorize(session, user, Action.EXEMPTION_READ, target_node=_node_of(session, s))
    ex_type = session.get(ExemptionType, ex.exemption_type_id) if ex.exemption_type_id else None
    include_sensitive = can_see_private(session, user, s)
    granted_by_name = None
    if ex.granted_by is not None:
        granter = session.get(Soldier, ex.granted_by)
        granted_by_name = granter.full_name if granter else None
    return ExemptionDetailOut(
        id=ex.id,
        exemption_type_name=ex_type.name if ex_type else "—",
        is_global=ex_type.is_global if ex_type else False,
        start_date=ex.start_date,
        end_date=ex.end_date,
        reason=ex.reason if include_sensitive else None,
        granted_by_name=granted_by_name,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_exemptions_api.py -v`
Expected: PASS (all tests, including the new ones)

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/exemptions.py backend/tests/integration/test_exemptions_api.py
git commit -m "feat: add exemption instance detail endpoint"
```

---

### Task 4: Frontend — types and API functions

**Files:**
- Modify: `frontend/src/api/exemptions.ts`
- Modify: `frontend/src/api/scoring.ts`
- Modify: `frontend/src/api/potential.ts`

**Interfaces:**
- Produces: `ExemptionSummaryItem` interface (in `api/exemptions.ts`, imported by `scoring.ts`/`potential.ts`); `ExemptionDetail` interface + `getExemptionDetail(soldierId, exemptionId)` function (in `api/exemptions.ts`). Used by Task 5 (`ExemptionsCell`) and Task 6 (`ExemptionInstanceModal`).

- [ ] **Step 1: Add the shared type and detail-fetch function**

In `frontend/src/api/exemptions.ts`, add after the existing `Exemption` interface (after line 11):

```typescript
export interface ExemptionSummaryItem {
  id: string;
  exemption_type_name: string;
  is_global: boolean;
  start_date: string;
  end_date: string | null;
}

export interface ExemptionDetail {
  id: string;
  exemption_type_name: string;
  is_global: boolean;
  start_date: string;
  end_date: string | null;
  reason: string | null;
  granted_by_name: string | null;
}

export async function getExemptionDetail(soldierId: string, exemptionId: string): Promise<ExemptionDetail> {
  return (await api.get<ExemptionDetail>(`/soldiers/${soldierId}/exemptions/${exemptionId}`)).data;
}
```

- [ ] **Step 2: Wire the type into `TransparencyRow`**

In `frontend/src/api/scoring.ts`, add the import (line 1) and field:

```typescript
import { api } from "./client";
import { ExemptionSummaryItem } from "./exemptions";

export interface TransparencyRow {
  soldier_id: string;
  full_name: string;
  node_id: string | null;
  node_name: string | null;
  enrolled_at: string;
  active_days: number;
  shift_count: number;
  rank: string | null;
  is_officer: boolean;
  service_type: "חובה" | "קבע" | null;
  cumulative_score: string;
  score_per_day: string;
  normalised_score: string;
  is_globally_exempted: boolean;
  effort_score: number;
  c_over_d: number;
  effort_offset_raw: number;
  exemptions_display: string;
  exemptions_visible: boolean;
  exemptions: ExemptionSummaryItem[];
  has_global_exemption: boolean | null;
  has_partial_exemption: boolean | null;
  has_temporary_exemption: boolean | null;
}
```

- [ ] **Step 3: Wire the type into `SoldierPotentialDetail`**

In `frontend/src/api/potential.ts`, add the import (line 1) and field:

```typescript
import { api } from "./client";
import { ExemptionSummaryItem } from "./exemptions";

export interface SoldierPotentialDetail {
  soldier_id: string;
  full_name: string;
  counted: boolean;
  reason: string | null;
  exemption_names: string[] | null;
  rank: string | null;
  partial_exemption_names: string[] | null;
  exemptions: ExemptionSummaryItem[] | null;
}
```

- [ ] **Step 4: Verify the frontend typechecks**

Run: `cd frontend && npm run typecheck`
Expected: PASS — these are additive fields/types, nothing consumes them yet so nothing should break.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/exemptions.ts frontend/src/api/scoring.ts frontend/src/api/potential.ts
git commit -m "feat: add exemption summary/detail types and API function"
```

---

### Task 5: Frontend — `ExemptionsCell` component

**Files:**
- Create: `frontend/src/components/ExemptionsCell.tsx`
- Create: `frontend/src/components/ExemptionsCell.test.tsx`
- Modify: `frontend/src/i18n/he.json`
- Modify: `frontend/src/utils/formatDate.ts` (add `formatDdMmYyyy`)

**Interfaces:**
- Consumes: `ExemptionSummaryItem` (Task 4).
- Produces: `<ExemptionsCell exemptions={...} visible={...} placeholder={...} soldierId={...} />`. Used by Tasks 7-8. Owns its own click→modal state (renders `ExemptionInstanceModal` from Task 6 internally). Also produces `formatDdMmYyyy(isoDate: string): string` in `frontend/src/utils/formatDate.ts`, consumed by Task 6.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/ExemptionsCell.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ExemptionsCell from "./ExemptionsCell";

vi.mock("../api/exemptions", async () => {
  const actual = await vi.importActual("../api/exemptions");
  return {
    ...actual,
    getExemptionDetail: vi.fn().mockResolvedValue({
      id: "ex-1", exemption_type_name: "פטור בדיקה", is_global: true,
      start_date: "2026-01-01", end_date: null, reason: null, granted_by_name: null,
    }),
  };
});

describe("ExemptionsCell", () => {
  it("renders the placeholder when not visible", () => {
    render(<ExemptionsCell exemptions={[]} visible={false} placeholder="חסוי" soldierId="s1" />);
    expect(screen.getByText("חסוי")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders a dash when visible but empty", () => {
    render(<ExemptionsCell exemptions={[]} visible={true} placeholder="חסוי" soldierId="s1" />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders a clickable chip with the end date suffix when present", () => {
    render(
      <ExemptionsCell
        exemptions={[{ id: "ex-1", exemption_type_name: "פטור בדיקה", is_global: true, start_date: "2026-01-01", end_date: "2026-05-01" }]}
        visible={true}
        placeholder="חסוי"
        soldierId="s1"
      />
    );
    expect(screen.getByRole("button", { name: "פטור בדיקה (עד 01/05/2026)" })).toBeInTheDocument();
  });

  it("renders a chip without a date suffix when end_date is null", () => {
    render(
      <ExemptionsCell
        exemptions={[{ id: "ex-1", exemption_type_name: "פטור בדיקה", is_global: true, start_date: "2026-01-01", end_date: null }]}
        visible={true}
        placeholder="חסוי"
        soldierId="s1"
      />
    );
    expect(screen.getByRole("button", { name: "פטור בדיקה" })).toBeInTheDocument();
  });

  it("opens the detail modal on click", () => {
    render(
      <ExemptionsCell
        exemptions={[{ id: "ex-1", exemption_type_name: "פטור בדיקה", is_global: true, start_date: "2026-01-01", end_date: null }]}
        visible={true}
        placeholder="חסוי"
        soldierId="s1"
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "פטור בדיקה" }));
    expect(screen.getByTestId("exemption-instance-modal")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- ExemptionsCell`
Expected: FAIL — `Cannot find module './ExemptionsCell'`.

- [ ] **Step 3: Add i18n keys**

In `frontend/src/i18n/he.json`, in the `"exemptions"` object (around line 161-173), add:

```json
  "exemptions": {
    "title": "פטורים",
    "type": "סוג פטור",
    "start_date": "מתאריך",
    "end_date": "עד תאריך",
    "reason": "סיבה",
    "grant": "הענק פטור",
    "revoke": "בטל",
    "none": "אין פטורים",
    "forever": "ללא הגבלה",
    "exempts_from": "פוטר מ",
    "past": "פטורים שפגו",
    "category_global": "גלובלי",
    "category_partial": "חלקי",
    "granted_by": "הוענק על ידי",
    "no_permission_details": "אין הרשאה לצפות בפרטים"
  },
```

- [ ] **Step 4: Add a shared slash-format date helper**

In `frontend/src/utils/formatDate.ts`, add a new export (after the existing `formatDutyRange` function, at the end of the file):

```typescript
/**
 * DD/MM/YYYY (slashes), matching the existing backend-formatted
 * exemptions_display string exactly (see scoring.py's _exemption_label) —
 * intentionally NOT the dot-separated format used elsewhere in this file,
 * since exemption chip/modal labels must read identically to what
 * Transparency already shows today.
 */
export function formatDdMmYyyy(isoDate: string): string {
  const [y, m, d] = isoDate.split("-");
  return `${d}/${m}/${y}`;
}
```

- [ ] **Step 5: Write minimal implementation**

Create `frontend/src/components/ExemptionsCell.tsx`:

```tsx
import { useState } from "react";
import { ExemptionSummaryItem } from "../api/exemptions";
import { formatDdMmYyyy } from "../utils/formatDate";
import ExemptionInstanceModal from "./ExemptionInstanceModal";

interface Props {
  exemptions: ExemptionSummaryItem[];
  visible: boolean;
  placeholder: string;
  soldierId: string;
}

function chipLabel(item: ExemptionSummaryItem): string {
  return item.end_date
    ? `${item.exemption_type_name} (עד ${formatDdMmYyyy(item.end_date)})`
    : item.exemption_type_name;
}

export default function ExemptionsCell({ exemptions, visible, placeholder, soldierId }: Props) {
  const [openExemptionId, setOpenExemptionId] = useState<string | null>(null);

  if (!visible) return <>{placeholder}</>;
  if (exemptions.length === 0) return <>—</>;

  return (
    <>
      <span className="flex flex-wrap gap-1">
        {exemptions.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setOpenExemptionId(item.id)}
            className="text-xs text-blue-600 dark:text-blue-400 underline"
          >
            {chipLabel(item)}
          </button>
        ))}
      </span>
      {openExemptionId && (
        <ExemptionInstanceModal
          soldierId={soldierId}
          exemptionId={openExemptionId}
          onClose={() => setOpenExemptionId(null)}
        />
      )}
    </>
  );
}
```

(This references `ExemptionInstanceModal`, built in Task 6 — this task's test mocks nothing about it directly except relying on it having `data-testid="exemption-instance-modal"`, which Task 6 must provide. Implement Task 6 immediately after this step, before running the test.)

- [ ] **Step 6: Run test to verify it passes**

Run: `cd frontend && npm test -- ExemptionsCell`
Expected: PASS (5 tests) — requires Task 6's `ExemptionInstanceModal` to exist first (see Task 6).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ExemptionsCell.tsx frontend/src/components/ExemptionsCell.test.tsx frontend/src/i18n/he.json frontend/src/utils/formatDate.ts
git commit -m "feat: add shared ExemptionsCell component"
```

---

### Task 6: Frontend — `ExemptionInstanceModal` component

**Files:**
- Create: `frontend/src/components/ExemptionInstanceModal.tsx`
- Create: `frontend/src/components/ExemptionInstanceModal.test.tsx`

**Interfaces:**
- Consumes: `getExemptionDetail` (Task 4), `ExemptionDetail` type (Task 4), `formatDdMmYyyy` (Task 5, added to `frontend/src/utils/formatDate.ts`).
- Produces: `<ExemptionInstanceModal soldierId={...} exemptionId={...} onClose={...} />`, rendering `data-testid="exemption-instance-modal"` on its outer wrapper. Consumed by Task 5's `ExemptionsCell`.

**Note:** Build this task's component before running Task 5's test suite (Task 5's `ExemptionsCell.test.tsx` imports it transitively).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/ExemptionInstanceModal.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ExemptionInstanceModal from "./ExemptionInstanceModal";
import * as exemptionsApi from "../api/exemptions";

describe("ExemptionInstanceModal", () => {
  it("renders type name, category, dates, reason, and granted-by on success", async () => {
    vi.spyOn(exemptionsApi, "getExemptionDetail").mockResolvedValue({
      id: "ex-1", exemption_type_name: "פטור רפואי", is_global: true,
      start_date: "2026-01-01", end_date: "2026-05-01", reason: "בעיה רפואית",
      granted_by_name: "יוסי כהן",
    });
    render(<ExemptionInstanceModal soldierId="s1" exemptionId="ex-1" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText("פטור רפואי")).toBeInTheDocument());
    expect(screen.getByText("01/01/2026")).toBeInTheDocument();
    expect(screen.getByText("01/05/2026")).toBeInTheDocument();
    expect(screen.getByText("בעיה רפואית")).toBeInTheDocument();
    expect(screen.getByText("יוסי כהן")).toBeInTheDocument();
  });

  it("shows 'forever' when end_date is null", async () => {
    vi.spyOn(exemptionsApi, "getExemptionDetail").mockResolvedValue({
      id: "ex-2", exemption_type_name: "פטור קבוע", is_global: false,
      start_date: "2026-01-01", end_date: null, reason: null, granted_by_name: null,
    });
    render(<ExemptionInstanceModal soldierId="s1" exemptionId="ex-2" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText("ללא הגבלה")).toBeInTheDocument());
  });

  it("shows a no-permission message on 403 without crashing", async () => {
    vi.spyOn(exemptionsApi, "getExemptionDetail").mockRejectedValue({
      response: { status: 403 },
    });
    render(<ExemptionInstanceModal soldierId="s1" exemptionId="ex-3" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText("אין הרשאה לצפות בפרטים")).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- ExemptionInstanceModal`
Expected: FAIL — `Cannot find module './ExemptionInstanceModal'`.

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/components/ExemptionInstanceModal.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ExemptionDetail, getExemptionDetail } from "../api/exemptions";
import { formatDdMmYyyy } from "../utils/formatDate";

interface Props {
  soldierId: string;
  exemptionId: string;
  onClose: () => void;
}

export default function ExemptionInstanceModal({ soldierId, exemptionId, onClose }: Props) {
  const { t } = useTranslation();
  const [detail, setDetail] = useState<ExemptionDetail | null>(null);
  const [forbidden, setForbidden] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getExemptionDetail(soldierId, exemptionId)
      .then((d) => { if (!cancelled) setDetail(d); })
      .catch((err: unknown) => {
        if (cancelled) return;
        const status = (err as { response?: { status?: number } })?.response?.status;
        if (status === 403) setForbidden(true);
      });
    return () => { cancelled = true; };
  }, [soldierId, exemptionId]);

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4"
      onClick={onClose}
      data-testid="exemption-instance-modal"
    >
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-md"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h3 className="font-semibold text-base">{t("exemptions.title")}</h3>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>

        {forbidden && (
          <p className="text-sm text-red-500">{t("exemptions.no_permission_details")}</p>
        )}

        {!forbidden && detail && (
          <div className="space-y-2 text-sm">
            <p className="font-medium">{detail.exemption_type_name}</p>
            <span className="inline-block text-xs bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200 px-2 py-0.5 rounded">
              {detail.is_global ? t("exemptions.category_global") : t("exemptions.category_partial")}
            </span>
            <p className="text-gray-700 dark:text-gray-300">
              {formatDdMmYyyy(detail.start_date)} → {detail.end_date ? formatDdMmYyyy(detail.end_date) : t("exemptions.forever")}
            </p>
            {detail.reason && (
              <p>
                <span className="font-medium">{t("exemptions.reason")}:</span> {detail.reason}
              </p>
            )}
            {detail.granted_by_name && (
              <p>
                <span className="font-medium">{t("exemptions.granted_by")}:</span> {detail.granted_by_name}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run both this task's and Task 5's tests to verify they pass**

Run: `cd frontend && npm test -- ExemptionInstanceModal ExemptionsCell`
Expected: PASS (8 tests total: 3 from this task, 5 from Task 5)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ExemptionInstanceModal.tsx frontend/src/components/ExemptionInstanceModal.test.tsx
git commit -m "feat: add shared ExemptionInstanceModal component"
```

---

### Task 7: Frontend — wire TransparencyPage

**Files:**
- Modify: `frontend/src/pages/TransparencyPage.tsx:569-575`

**Interfaces:**
- Consumes: `ExemptionsCell` (Task 5).

- [ ] **Step 1: Update the import**

In `frontend/src/pages/TransparencyPage.tsx`, add the import near the other component imports (around line 10):

```tsx
import SoldierLink from "../components/SoldierLink";
import ExemptionsCell from "../components/ExemptionsCell";
```

- [ ] **Step 2: Replace the exemptions column cell**

Replace the `exemptions` column definition (lines 569-575):

```tsx
    {
      id: "exemptions", header: t("transparency.exemptions"),
      cell: (r) => (
        <ExemptionsCell
          exemptions={r.exemptions}
          visible={r.exemptions_visible}
          placeholder="חסוי"
          soldierId={r.soldier_id}
        />
      ),
      sortValue: (r) => r.exemptions_display,
      filterValue: (r) => r.exemptions_display,
      exportValue: (r) => r.exemptions_display || "—",
    },
```

(`sortValue`/`filterValue`/`exportValue` are unchanged — they keep using the existing flat `exemptions_display` string, since sorting/filtering/CSV export don't need the interactive chip rendering.)

- [ ] **Step 3: Verify typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: PASS

- [ ] **Step 4: Manually verify in the browser**

Start the dev server (or ensure it's running), navigate to the Transparency page, and confirm: soldiers with visible exemptions show clickable chips with "(עד DD/MM/YYYY)" when applicable; soldiers without hierarchy scope show "חסוי" as before; clicking a chip opens the detail modal with dates/reason/granted-by.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/TransparencyPage.tsx
git commit -m "feat: wire TransparencyPage to shared ExemptionsCell"
```

---

### Task 8: Frontend — wire PotentialPage

**Files:**
- Modify: `frontend/src/pages/planning/PotentialPage.tsx`

**Interfaces:**
- Consumes: `ExemptionsCell` (Task 5).
- Removes: `openExemptionModal`, `viewingExemption` state, the `exemptionTypes`/`exemptionDutyMap`/`dutyTypes`/`canEditExemptions` state and their fetch effect, and the `ExemptionTypeViewModal` usage block — all exclusive to this page's old wiring (confirmed via grep: no other usage in this file).

- [ ] **Step 1: Remove the old exemption-type-modal state and fetch effect**

Remove these lines (47-53):

```tsx
  const { user } = useAuth();
  const canEditExemptions = user?.role === "admin" || !!user?.is_duty_manager;
  const [exemptionTypes, setExemptionTypes] = useState<ExemptionType[]>([]);
  const [exemptionDutyMap, setExemptionDutyMap] = useState<Record<string, string[]>>({});
  const [dutyTypes, setDutyTypes] = useState<DutyType[]>([]);
  const [viewingExemption, setViewingExemption] = useState<ExemptionType | null>(null);
```

Replace with just:

```tsx
  const { user } = useAuth();
```

(`user` stays — check whether anything else in the file uses `user` besides `canEditExemptions`; if nothing else does, `useAuth()`'s import and the `user` variable can be removed too — grep the file for other `user?.` / `user.` usages before deleting.)

Remove the fetch effect (lines 105-113):

```tsx
  useEffect(() => {
    Promise.all([listExemptionTypes(), getAllExemptionDutyTypeMaps(), listDutyTypes()]).then(
      ([ets, map, dts]) => {
        setExemptionTypes(ets);
        setExemptionDutyMap(map);
        setDutyTypes(dts);
      },
    );
  }, []);
```

Remove the now-unused imports (lines 24-31):

```tsx
import ExemptionTypeViewModal from "../../components/ExemptionTypeViewModal";
import {
  DutyType,
  ExemptionType,
  getAllExemptionDutyTypeMaps,
  listDutyTypes,
  listExemptionTypes,
} from "../../api/dutyConfig";
```

Add the new import in their place:

```tsx
import ExemptionsCell from "../../components/ExemptionsCell";
```

Remove the now-unused `openExemptionModal` helper (lines 200-203):

```tsx
  function openExemptionModal(name: string) {
    const et = exemptionTypes.find((e) => e.name === name);
    if (et) setViewingExemption(et);
  }
```

- [ ] **Step 2: Replace the reason column's cell renderer**

Replace the `reason` column's `cell` (lines 344-367), keeping `reasonText` unchanged (still used for `filterValue`):

```tsx
    {
      id: "reason",
      header: t("potential.reason_col"),
      cell: (s) => {
        if (s.counted && (!s.partial_exemption_names || s.partial_exemption_names.length === 0)) {
          return "—";
        }
        if (s.counted || s.reason === "exempted") {
          return (
            <ExemptionsCell
              exemptions={s.exemptions ?? []}
              visible={s.exemption_names !== null}
              placeholder={t("potential.reason_exempted_restricted")}
              soldierId={s.soldier_id}
            />
          );
        }
        return reasonText(s);
      },
      filterValue: (s) => reasonText(s),
    },
```

- [ ] **Step 3: Remove the `ExemptionTypeViewModal` render block**

Remove (lines 443-456):

```tsx
      {viewingExemption && (
        <ExemptionTypeViewModal
          exemptionType={viewingExemption}
          mappedDutyTypeIds={exemptionDutyMap[viewingExemption.id] ?? []}
          dutyTypes={dutyTypes}
          canEdit={canEditExemptions}
          onClose={() => setViewingExemption(null)}
          onSaved={(updated, mappedIds) => {
            setExemptionTypes((prev) => prev.map((e) => (e.id === updated.id ? updated : e)));
            setExemptionDutyMap((prev) => ({ ...prev, [updated.id]: mappedIds }));
            setViewingExemption(updated);
          }}
        />
      )}
```

- [ ] **Step 4: Verify typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: PASS — if `user`/`useAuth` becomes fully unused, lint will flag it; remove that import too in that case.

- [ ] **Step 5: Manually verify in the browser**

Navigate to the Potential planning page, expand a node. Confirm: soldiers with partial exemptions show clickable chips with end-date suffix when applicable; soldiers fully exempted (reason "exempted") now ALSO show clickable chips (previously plain text); clicking any chip opens the same detail modal used on Transparency; restricted (not-authorized) cases show the existing `reason_exempted_restricted` placeholder text unchanged.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/planning/PotentialPage.tsx
git commit -m "feat: wire PotentialPage to shared ExemptionsCell, remove old modal wiring"
```

---

## Post-implementation checklist

- [ ] Run the full backend fast suite: `cd backend && pytest -q`
- [ ] Run `cd frontend && npm run lint && npm run typecheck && npm test`
- [ ] Confirm `ExemptionTypeViewModal.test.tsx` still passes unmodified (its only production usage was removed from `PotentialPage.tsx`, but the component itself and its test are untouched — verify nothing else references it before considering it dead code; if it's now unused anywhere in the app, that's a separate cleanup decision, not part of this plan)
- [ ] Update `frontend/CHANGELOG.md` per the project's daily-changelog convention before merging
