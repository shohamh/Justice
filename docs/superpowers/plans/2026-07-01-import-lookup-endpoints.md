# Import-support lookup endpoints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three read-only, duty-manager/admin-gated lookup endpoints (duty types, hierarchy, soldiers) that an Excel import parser can call to validate references while parsing, plus a markdown guide documenting the import format and how to use them.

**Architecture:** One new FastAPI router file (`backend/app/routes/import_lookup.py`) reusing existing Pydantic output models from `duty_config.py` and `hierarchy.py` for the first two endpoints, and a new lightweight `SoldierLookupOut` model for the third. All three depend on the existing `require_duty_manager_or_admin` dependency. One new test file. One new docs file.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (Session, `select`), Pydantic, pytest (TestClient, testcontainers Postgres — see `backend/tests/conftest.py`).

---

### Task 1: Duty-types and hierarchy lookup endpoints

**Files:**
- Create: `backend/app/routes/import_lookup.py`
- Modify: `backend/app/main.py` (register router)
- Test: `backend/tests/integration/test_import_lookup.py`

- [ ] **Step 1: Write the failing tests for `/duty-types` and `/hierarchy`**

```python
from __future__ import annotations

from decimal import Decimal

from app.db.models import DutyType
from tests.helpers import auth_headers, create_node, create_soldier


def test_duty_types_requires_duty_manager_or_admin(client, admin_session):
    soldier = create_soldier(admin_session, personal_number="il_soldier_001")
    resp = client.get("/api/import-lookup/duty-types", headers=auth_headers(soldier))
    assert resp.status_code == 403


def test_duty_types_returns_active_and_inactive(client, admin_session):
    node = create_node(admin_session, level="branch", name="il_node_001")
    dm = create_soldier(admin_session, personal_number="il_dm_001", role="duty_manager", hierarchy_node_id=node.id)
    active = DutyType(name="il_active_type", score_per_day=Decimal("1.00"))
    inactive = DutyType(name="il_inactive_type", score_per_day=Decimal("1.00"), active=False)
    admin_session.add_all([active, inactive])
    admin_session.commit()

    resp = client.get("/api/import-lookup/duty-types", headers=auth_headers(dm))
    assert resp.status_code == 200
    names = {row["name"] for row in resp.json()}
    assert "il_active_type" in names
    assert "il_inactive_type" in names


def test_hierarchy_requires_duty_manager_or_admin(client, admin_session):
    soldier = create_soldier(admin_session, personal_number="il_soldier_002")
    resp = client.get("/api/import-lookup/hierarchy", headers=auth_headers(soldier))
    assert resp.status_code == 403


def test_hierarchy_returns_full_tree_regardless_of_dm_scope(client, admin_session):
    root = create_node(admin_session, level="branch", name="il_root_001")
    other = create_node(admin_session, level="branch", name="il_other_001")
    dm = create_soldier(admin_session, personal_number="il_dm_002", role="duty_manager", hierarchy_node_id=root.id)

    resp = client.get("/api/import-lookup/hierarchy", headers=auth_headers(dm))
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.json()}
    assert str(root.id) in ids
    assert str(other.id) in ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv\Scripts\python -m pytest tests/integration/test_import_lookup.py -v`
Expected: FAIL — `404 Not Found` (route doesn't exist yet).

- [ ] **Step 3: Create the router with `/duty-types` and `/hierarchy` endpoints**

```python
# backend/app/routes/import_lookup.py
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_duty_manager_or_admin
from app.db.models import DutyType, HierarchyNode, Soldier
from app.db.session import get_session
from app.routes.duty_config import DutyTypeOut, _dt_out
from app.routes.hierarchy import NodeOut, _out
from app.auth.authz import is_commander, is_duty_manager, scope_root_ids

router = APIRouter(prefix="/import-lookup", tags=["import-lookup"])


@router.get("/duty-types", response_model=list[DutyTypeOut])
def list_duty_types_for_import(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_duty_manager_or_admin),
) -> list[DutyTypeOut]:
    return [_dt_out(d) for d in session.execute(select(DutyType)).scalars().all()]


@router.get("/hierarchy", response_model=list[NodeOut])
def list_hierarchy_for_import(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_duty_manager_or_admin),
) -> list[NodeOut]:
    nodes = list(session.execute(select(HierarchyNode)).scalars().all())
    user_roots = scope_root_ids(session, user)
    user_is_commander = is_commander(session, user.id)
    user_is_duty_manager = is_duty_manager(session, user.id)
    return [
        _out(
            n, session, user=user,
            user_roots=user_roots,
            user_is_commander=user_is_commander,
            user_is_duty_manager=user_is_duty_manager,
        )
        for n in nodes
    ]
```

- [ ] **Step 4: Register the router in `main.py`**

Add the import near the other route imports (after line 44, alphabetically grouped with the others):

```python
from app.routes import import_lookup as import_lookup_routes
```

Add the include_router call after `import_excel_routes` (currently `backend/app/main.py:161`):

```python
    app.include_router(import_excel_routes.router, prefix="/api")
    app.include_router(import_lookup_routes.router, prefix="/api")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .venv\Scripts\python -m pytest tests/integration/test_import_lookup.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/import_lookup.py backend/app/main.py backend/tests/integration/test_import_lookup.py
git commit -m "feat: add import-lookup endpoints for duty types and hierarchy"
```

---

### Task 2: Soldiers lookup endpoint

**Files:**
- Modify: `backend/app/routes/import_lookup.py`
- Test: `backend/tests/integration/test_import_lookup.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/integration/test_import_lookup.py`:

```python
def test_soldiers_requires_at_least_one_filter(client, admin_session):
    node = create_node(admin_session, level="branch", name="il_node_003")
    dm = create_soldier(admin_session, personal_number="il_dm_003", role="duty_manager", hierarchy_node_id=node.id)
    resp = client.get("/api/import-lookup/soldiers", headers=auth_headers(dm))
    assert resp.status_code == 400
    assert resp.json()["detail"] == "no_filter_provided"


def test_soldiers_lookup_by_personal_number(client, admin_session):
    node = create_node(admin_session, level="branch", name="il_node_004")
    dm = create_soldier(admin_session, personal_number="il_dm_004", role="duty_manager", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number="il_target_004", hierarchy_node_id=node.id)

    resp = client.get(
        "/api/import-lookup/soldiers",
        params={"personal_number": "il_target_004"},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["personal_number"] == "il_target_004"
    assert rows[0]["full_name"] == target.full_name
    assert rows[0]["hierarchy_node_name"] == "il_node_004"


def test_soldiers_lookup_by_partial_name_case_insensitive(client, admin_session):
    node = create_node(admin_session, level="branch", name="il_node_005")
    dm = create_soldier(admin_session, personal_number="il_dm_005", role="duty_manager", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number="il_target_005", hierarchy_node_id=node.id)
    target.full_name = "Israel Israeli"
    admin_session.commit()

    resp = client.get(
        "/api/import-lookup/soldiers",
        params={"name": "israel isr"},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["personal_number"] == "il_target_005"


def test_soldiers_lookup_by_hierarchy_includes_descendants(client, admin_session):
    top = create_node(admin_session, level="branch", name="il_top_006")
    mid = create_node(admin_session, level="unit", name="il_mid_006", parent=top)
    leaf = create_node(admin_session, level="squad", name="il_leaf_006", parent=mid)
    dm = create_soldier(admin_session, personal_number="il_dm_006", role="duty_manager", hierarchy_node_id=top.id)
    direct = create_soldier(admin_session, personal_number="il_direct_006", hierarchy_node_id=top.id)
    grandchild = create_soldier(admin_session, personal_number="il_grandchild_006", hierarchy_node_id=leaf.id)
    elsewhere_node = create_node(admin_session, level="branch", name="il_elsewhere_006")
    outside = create_soldier(admin_session, personal_number="il_outside_006", hierarchy_node_id=elsewhere_node.id)

    resp = client.get(
        "/api/import-lookup/soldiers",
        params={"hierarchy_node_id": str(top.id)},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    numbers = {row["personal_number"] for row in resp.json()}
    assert numbers == {"il_direct_006", "il_grandchild_006"}
    assert "il_outside_006" not in numbers


def test_soldiers_lookup_combines_filters_with_and(client, admin_session):
    node = create_node(admin_session, level="branch", name="il_node_007")
    other_node = create_node(admin_session, level="branch", name="il_other_007")
    dm = create_soldier(admin_session, personal_number="il_dm_007", role="duty_manager", hierarchy_node_id=node.id)
    inside = create_soldier(admin_session, personal_number="il_inside_007", hierarchy_node_id=node.id)
    inside.full_name = "Shared Name"
    outside = create_soldier(admin_session, personal_number="il_outside_007", hierarchy_node_id=other_node.id)
    outside.full_name = "Shared Name"
    admin_session.commit()

    resp = client.get(
        "/api/import-lookup/soldiers",
        params={"name": "Shared Name", "hierarchy_node_id": str(node.id)},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    numbers = {row["personal_number"] for row in resp.json()}
    assert numbers == {"il_inside_007"}


def test_soldiers_lookup_no_matches_returns_empty_list(client, admin_session):
    node = create_node(admin_session, level="branch", name="il_node_008")
    dm = create_soldier(admin_session, personal_number="il_dm_008", role="duty_manager", hierarchy_node_id=node.id)
    resp = client.get(
        "/api/import-lookup/soldiers",
        params={"personal_number": "does_not_exist"},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    assert resp.json() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv\Scripts\python -m pytest tests/integration/test_import_lookup.py -v -k soldiers`
Expected: FAIL — `404 Not Found` (route doesn't exist yet).

- [ ] **Step 3: Implement the soldiers endpoint**

Append to `backend/app/routes/import_lookup.py` (add `or_` to the sqlalchemy import at the top: `from sqlalchemy import or_, select`):

```python
class SoldierLookupOut(BaseModel):
    id: uuid.UUID
    personal_number: str
    full_name: str
    rank: str | None
    hierarchy_node_id: uuid.UUID | None
    hierarchy_node_name: str | None


@router.get("/soldiers", response_model=list[SoldierLookupOut])
def lookup_soldiers_for_import(
    personal_number: str | None = None,
    name: str | None = None,
    hierarchy_node_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_duty_manager_or_admin),
) -> list[SoldierLookupOut]:
    if personal_number is None and name is None and hierarchy_node_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="no_filter_provided")

    query = select(Soldier)
    if personal_number is not None:
        query = query.where(Soldier.personal_number == personal_number)
    if name is not None:
        query = query.where(Soldier.full_name.ilike(f"%{name}%"))
    if hierarchy_node_id is not None:
        descendant_ids = session.execute(
            select(HierarchyNode.id).where(
                or_(
                    HierarchyNode.id == hierarchy_node_id,
                    HierarchyNode.path_ids.any(hierarchy_node_id),
                )
            )
        ).scalars().all()
        query = query.where(Soldier.hierarchy_node_id.in_(descendant_ids))

    soldiers = list(session.execute(query).scalars().all())

    node_ids = {s.hierarchy_node_id for s in soldiers if s.hierarchy_node_id}
    nodes_by_id: dict[uuid.UUID, HierarchyNode] = {}
    if node_ids:
        nodes_by_id = {
            n.id: n for n in session.execute(
                select(HierarchyNode).where(HierarchyNode.id.in_(node_ids))
            ).scalars().all()
        }

    return [
        SoldierLookupOut(
            id=s.id,
            personal_number=s.personal_number,
            full_name=s.full_name,
            rank=s.rank,
            hierarchy_node_id=s.hierarchy_node_id,
            hierarchy_node_name=nodes_by_id[s.hierarchy_node_id].name if s.hierarchy_node_id in nodes_by_id else None,
        )
        for s in soldiers
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv\Scripts\python -m pytest tests/integration/test_import_lookup.py -v`
Expected: PASS (10 tests total)

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/import_lookup.py backend/tests/integration/test_import_lookup.py
git commit -m "feat: add soldier lookup endpoint with name/personal-number/hierarchy filters"
```

---

### Task 3: Register test file under the `soldiers` pytest area marker

**Files:**
- Modify: `backend/tests/conftest.py:87-90`

- [ ] **Step 1: Add the mapping entry**

In `backend/tests/conftest.py`, find:

```python
    # soldiers: soldier profile, soldier listing, Excel import
    "test_soldier_profile": "soldiers",
    "test_soldiers_api": "soldiers",
    "test_import_excel": "soldiers",
```

Change to:

```python
    # soldiers: soldier profile, soldier listing, Excel import
    "test_soldier_profile": "soldiers",
    "test_soldiers_api": "soldiers",
    "test_import_excel": "soldiers",
    "test_import_lookup": "soldiers",
```

- [ ] **Step 2: Verify the marker applies**

Run: `cd backend && .venv\Scripts\python -m pytest tests/integration/test_import_lookup.py -v -m soldiers`
Expected: PASS (10 tests — same 10 as Task 1+2, confirming the marker selects them)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/conftest.py
git commit -m "test: map test_import_lookup to the soldiers pytest area marker"
```

---

### Task 4: Parser guide documentation

**Files:**
- Create: `docs/excel-import-parser-guide.md`

- [ ] **Step 1: Read the current import implementation to transcribe accurate column lists**

Run: `cd backend && grep -n "def parse_\|columns\|expected" app/routes/import_excel.py | head -40`

Confirm the exact column names/order per sheet against `backend/app/routes/import_excel.py` before writing the doc (the plan below reflects the columns found during design-phase exploration — verify against the live file since these are load-bearing for parser authors).

- [ ] **Step 2: Write the doc**

```markdown
# Writing an Excel import parser

This guide explains the import pipeline's expected spreadsheet format and the
API endpoints available to validate data while building or maintaining an
import parser. It's written for both human engineers and coding agents.

## Pipeline overview

Import is a two-step flow, implemented in `backend/app/routes/import_excel.py`:

1. `POST /api/import/preview` — upload an `.xlsx` file. The server parses it
   and returns a preview of what would be created/updated, without writing
   anything to the database.
2. `POST /api/import/apply` — submit the (optionally edited) preview payload
   to actually commit the changes.

Both endpoints require a duty manager or admin token
(`require_duty_manager_or_admin` + `require_password_changed` in
`backend/app/auth/deps.py`).

## Expected sheet formats

The workbook may contain up to three sheets, each optional: `soldiers`,
`assignments`, `shift_templates`.

### `soldiers` sheet columns

`personal_number`, `full_name`, `rank`, `gender`, `is_officer`,
`hierarchy_node_name`, `enrolled_at`, `enlistment_date`, `phone`, `email`

- `personal_number` is the unique key: if it matches an existing soldier,
  the row becomes an update; otherwise it's a new soldier.
- `hierarchy_node_name` must match a node in the current hierarchy tree —
  validate it against `GET /api/import-lookup/hierarchy` before generating
  rows that reference it (see below).

### `assignments` sheet columns

`personal_number`, `duty_type_name`, `start_date`, `end_date`, `is_reserve`

- `personal_number` must reference a soldier — new or already existing.
- `duty_type_name` must match an existing duty type — validate against
  `GET /api/import-lookup/duty-types`.
- Dates accept `dd.mm.yyyy` or ISO `yyyy-mm-dd`.

### `shift_templates` sheet columns

`name`, `duty_type_name`, `days_of_week`, `required_primary`, `required_reserve`

- `duty_type_name` must match an existing duty type, same as above.
- `days_of_week` is a comma-separated list.

## Validating data while parsing

Three read-only endpoints exist specifically to support parser development
and debugging. All three require a duty manager or admin token
(`require_duty_manager_or_admin`) — the same auth level needed to run the
import itself.

### `GET /api/import-lookup/duty-types`

Returns every duty type (active and inactive) with full fields. Use this to
confirm a `duty_type_name` from a sheet is real before emitting a row that
references it — an unrecognized name should be flagged as a parse error
rather than silently sent to `/api/import/apply`.

```
GET /api/import-lookup/duty-types
Authorization: Bearer <token>

200 OK
[
  {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "name": "משמר לילה",
    "score_per_day": "1.50",
    "active": true,
    ...
  }
]
```

### `GET /api/import-lookup/hierarchy`

Returns every hierarchy node, regardless of the caller's own duty-manager
scope. Use this to resolve a `hierarchy_node_name` from the sheet to a node
`id`, and to confirm the name isn't ambiguous (names are not guaranteed
globally unique — check `parent_id`/`path_ids` if a sheet's name matches
more than one node).

```
GET /api/import-lookup/hierarchy
Authorization: Bearer <token>

200 OK
[
  {
    "id": "...",
    "level": "unit",
    "name": "יחידה 1",
    "parent_id": "...",
    "path_ids": ["...", "..."],
    ...
  }
]
```

### `GET /api/import-lookup/soldiers`

Look up soldiers by `personal_number` (exact), `name` (case-insensitive
partial match), and/or `hierarchy_node_id` (includes all descendant nodes,
not just direct members). At least one filter is required — a request with
none returns `400 no_filter_provided`. Filters combine with AND. No matches
returns `200` with an empty list.

```
GET /api/import-lookup/soldiers?personal_number=1234567
Authorization: Bearer <token>

200 OK
[
  {
    "id": "...",
    "personal_number": "1234567",
    "full_name": "ישראל ישראלי",
    "rank": "רב\"ט",
    "hierarchy_node_id": "...",
    "hierarchy_node_name": "יחידה 1"
  }
]
```

Typical use: before treating a sheet row as a "new soldier," check whether
`personal_number` already exists via this endpoint — this mirrors what
`/api/import/preview` itself does internally, and is useful for a parser
that wants to pre-flag likely duplicates (e.g. same name, different
personal number) before the row ever reaches the import endpoints.
```

- [ ] **Step 3: Verify the doc's column lists match the implementation**

Run: `cd backend && grep -n "\"personal_number\"\|\"duty_type_name\"\|\"days_of_week\"" app/routes/import_excel.py`
Confirm every column name in the doc appears in the implementation output. Fix any mismatch in the doc before committing.

- [ ] **Step 4: Commit**

```bash
git add docs/excel-import-parser-guide.md
git commit -m "docs: add Excel import parser guide covering format and lookup endpoints"
```
