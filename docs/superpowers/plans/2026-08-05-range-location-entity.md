# Range Location Entity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `RangeEvent.location` from a free-text `Text` column into a real `RangeLocation` entity (mirroring the existing `DutyLocation` pattern), so a range event's location can no longer be an arbitrary, un-normalized string.

**Architecture:** A new `range_locations` table (id, name, active, timestamps) is added; `RangeEvent.location` is replaced by a `range_location_id` FK. A migration backfills one `RangeLocation` row per distinct existing `location` string and repoints existing events before dropping the old column. `RangeEventOut` keeps exposing a `location: str` field for read-only display (now resolved via join instead of a raw column) plus a new `range_location_id: str` field for the edit form — this means `RangesPage.tsx`'s modal title and `RangeEditAssignmentsModal.tsx`'s subtitle need **no code changes** at all, only `RangeFormModal.tsx` (create/edit form, needs a location picker) and `RangePlanningTable.tsx` (location link becomes plain text) change on the frontend.

**Tech Stack:** FastAPI + Pydantic + SQLAlchemy + Alembic (backend/), React + TypeScript + Vitest (frontend/), pytest (backend tests).

## Global Constraints

- Mirror the existing `DutyLocation` pattern exactly where the spec says so: same column shape (`id`, `name`, `active`, `created_at`, `updated_at` — no `base` column, unlike `DutyLocation`), same auth gating style (`GET` open to any password-changed user, `POST` gated to `require_config_manager`).
- `RangeFormModal.tsx` submission must only ever send a `range_location_id`, never a free string — a nonexistent location must be impossible to save.
- FK from `range_events.range_location_id` to `range_locations.id` uses `ondelete="RESTRICT"`, matching the existing `duty_assignments.duty_location_id -> duty_locations.id` convention in `backend/app/db/models.py`.

---

## Task 1: `RangeLocation` model + migration (table only, no FK on `range_events` yet)

**Files:**
- Modify: `backend/app/db/models.py` (insert new class before `class RangeEvent(Base):`, currently around line 825)
- Create: `backend/alembic/versions/<generated>_create_range_locations.py`
- Test: `backend/app/services/tests/test_range_locations.py` (new)

**Interfaces:**
- Produces: `RangeLocation` ORM class with `id: uuid.UUID`, `name: str`, `active: bool` (default `True`), `created_at`/`updated_at`, table name `range_locations`.

- [ ] **Step 1: Write the failing test**

Create `backend/app/services/tests/test_range_locations.py`:

```python
from __future__ import annotations


def test_range_location_can_be_created_with_defaults(app_session):
    from app.db.models import RangeLocation

    loc = RangeLocation(name="מטווח בדיקה")
    app_session.add(loc)
    app_session.flush()

    assert loc.id is not None
    assert loc.active is True
    assert loc.created_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/app/services/tests/test_range_locations.py -v`
Expected: FAIL (`ImportError: cannot import name 'RangeLocation'`)

- [ ] **Step 3: Add the model**

In `backend/app/db/models.py`, insert immediately before `class RangeEvent(Base):` (the class right after the `RangeEventStatus` enum, currently around line 825):

```python
class RangeLocation(Base):
    __tablename__ = "range_locations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    name: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

(This mirrors `DutyLocation` at `backend/app/db/models.py:212-226` minus the `base` column — the spec explicitly lists only `id, name, active, timestamps`.)

- [ ] **Step 4: Generate and fill in the migration**

From `backend/`, with the venv active, run:

```bash
alembic revision -m "create range_locations"
```

This creates a new file in `alembic/versions/` with an auto-generated revision id and `down_revision` set to whatever `alembic heads` currently reports (confirmed at plan-writing time to be `5923458a9996`, but re-run `alembic heads` yourself since other work may have landed a new head since). Edit the generated file's `upgrade()`/`downgrade()` to:

```python
def upgrade() -> None:
    op.create_table(
        "range_locations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("range_locations")
```

Add `from sqlalchemy.dialects import postgresql` to the generated file's imports if not already present (mirroring `backend/alembic/versions/0008_create_duty_locations.py`).

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/app/services/tests/test_range_locations.py -v`
Expected: PASS (the test fixture DB is created fresh from models via SQLAlchemy metadata in this repo's test setup — check `backend/tests/conftest.py`'s `app_session` fixture if this fails with a "table does not exist" error, and apply the migration to the test DB per that fixture's existing setup pattern before retrying)

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/*_create_range_locations.py backend/app/services/tests/test_range_locations.py
git commit -m "feat: add RangeLocation model and range_locations table"
```

---

## Task 2: `GET`/`POST /range-locations` routes + service

**Files:**
- Create: `backend/app/services/range_locations.py`
- Create: `backend/app/routes/range_locations.py`
- Modify: `backend/app/main.py` (register the new router)
- Test: `backend/tests/integration/test_range_locations_api.py` (new)

**Interfaces:**
- Consumes: `RangeLocation` (Task 1), `require_password_changed`/`require_duty_manager_or_admin` from `app.auth.deps` (existing).
- Produces: `create_range_location(session, *, name: str, actor_id: uuid.UUID | None = None) -> RangeLocation` (service). Routes: `GET /api/range-locations` (any password-changed user), `POST /api/range-locations` (config-manager gated, 201, body `{"name": str}`, response `{"id", "name", "active"}`).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/integration/test_range_locations_api.py`:

```python
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def test_plain_soldier_can_list_range_locations(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="6100001")
    r = client.get("/api/range-locations", headers=auth_headers(s))
    assert r.status_code == 200


def test_duty_manager_can_create_range_location(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="department", name="rl-dm-node")
    dm = create_soldier(admin_session, personal_number="6100002", role="duty_manager", hierarchy_node_id=node.id)
    r = client.post("/api/range-locations", headers=auth_headers(dm), json={"name": "מטווח חדש"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "מטווח חדש"
    assert body["active"] is True

    r2 = client.get("/api/range-locations", headers=auth_headers(dm))
    assert any(loc["id"] == body["id"] for loc in r2.json())


def test_plain_soldier_cannot_create_range_location(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="6100003")
    r = client.post("/api/range-locations", headers=auth_headers(s), json={"name": "should_not_be_allowed"})
    assert r.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/integration/test_range_locations_api.py -v`
Expected: FAIL (404 — route doesn't exist yet)

- [ ] **Step 3: Implement the service**

Create `backend/app/services/range_locations.py`:

```python
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import RangeLocation


def create_range_location(
    session: Session, *, name: str, actor_id: uuid.UUID | None = None
) -> RangeLocation:
    loc = RangeLocation(name=name)
    session.add(loc)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="range_location.create",
        entity_type="range_location",
        entity_id=loc.id,
        after={"name": name},
    )
    return loc
```

(Mirrors `create_location` in `backend/app/services/duty_config.py:184-198`.)

- [ ] **Step 4: Implement the routes**

Create `backend/app/routes/range_locations.py`:

```python
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_duty_manager_or_admin, require_password_changed
from app.db.models import RangeLocation, Soldier
from app.db.session import get_session
from app.services import range_locations as svc

router = APIRouter(prefix="/range-locations", tags=["range-locations"])


def require_config_manager(
    user: Soldier = Depends(require_duty_manager_or_admin),
) -> Soldier:
    if user.must_change_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="must_change_password")
    return user


class RangeLocationOut(BaseModel):
    id: uuid.UUID
    name: str
    active: bool


class CreateRangeLocationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


def _out(loc: RangeLocation) -> RangeLocationOut:
    return RangeLocationOut(id=loc.id, name=loc.name, active=loc.active)


@router.get("", response_model=list[RangeLocationOut])
def list_range_locations(
    session: Session = Depends(get_session), user: Soldier = Depends(require_password_changed)
) -> list[RangeLocationOut]:
    return [_out(loc) for loc in session.execute(select(RangeLocation)).scalars().all()]


@router.post("", response_model=RangeLocationOut, status_code=status.HTTP_201_CREATED)
def create_range_location(
    body: CreateRangeLocationRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_config_manager),
) -> RangeLocationOut:
    loc = svc.create_range_location(session, name=body.name, actor_id=user.id)
    session.commit()
    session.refresh(loc)
    return _out(loc)
```

(Mirrors `backend/app/routes/duty_config.py`'s `list_locations`/`create_location` at lines 286-322, but as its own top-level router with prefix `/range-locations` rather than nested under `/duty-config`, since it is a distinct resource from `DutyLocation`.)

In `backend/app/main.py`, add the import alongside the other route imports (near `from app.routes import ranges as ranges_routes`):

```python
from app.routes import range_locations as range_locations_routes
```

and register it alongside `app.include_router(ranges_routes.router, prefix="/api")`:

```python
    app.include_router(range_locations_routes.router, prefix="/api")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/tests/integration/test_range_locations_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/range_locations.py backend/app/routes/range_locations.py backend/app/main.py backend/tests/integration/test_range_locations_api.py
git commit -m "feat: add GET/POST /range-locations endpoints"
```

---

## Task 3: Migrate `RangeEvent.location` (Text) to `range_location_id` (FK) — model, migration, service, routes

This is the breaking-change core of the feature: it must land as one unit because a half-migrated state (e.g. model changed but service/routes not updated) won't import.

**Files:**
- Modify: `backend/app/db/models.py` (`RangeEvent.location` column)
- Create: `backend/alembic/versions/<generated>_migrate_range_event_location_to_fk.py`
- Modify: `backend/app/services/ranges.py` (`create_range_event`, `update_range_event`, `_range_context`)
- Modify: `backend/app/routes/ranges.py` (`CreateRangeEventBody`, `UpdateRangeEventBody`, `RangeEventOut`, `_event_out`, `create_range_event` route)
- Modify: `backend/tests/helpers.py` (add `create_range_location` test helper)
- Modify: every backend test file listed in Step 6 below

**Interfaces:**
- Consumes: `RangeLocation` (Task 1).
- Produces: `RangeEvent.range_location_id: uuid.UUID` (replaces `location`). `create_range_event(..., range_location_id: uuid.UUID, ...)` and `update_range_event(..., range_location_id: uuid.UUID | object = _UNSET, ...)` (renamed from `location`). `RangeEventOut` gains `range_location_id: uuid.UUID` and keeps `location: str` — now populated by resolving the joined `RangeLocation.name` in `_event_out`, not a raw column.

- [ ] **Step 1: Add the `create_range_location` test helper**

In `backend/tests/helpers.py`, add (mirroring `create_duty_location` at line 64-68) and add `RangeLocation` to the existing `from app.db.models import DutyLocation, DutyManagerScope, HierarchyNode, Soldier` import line:

```python
def create_range_location(session: Session, *, name: str = "מיקום מטווח בדיקה") -> RangeLocation:
    location = RangeLocation(name=name)
    session.add(location)
    session.flush()
    return location
```

- [ ] **Step 2: Update the model**

In `backend/app/db/models.py`, in `class RangeEvent(Base):`, change:

```python
    location: Mapped[str] = mapped_column(Text)
```

to:

```python
    range_location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("range_locations.id", ondelete="RESTRICT")
    )
```

(Keep the column in the same position in the class body — right after `date`.)

- [ ] **Step 3: Write the migration**

From `backend/`, run:

```bash
alembic revision -m "migrate range_events location to range_location_id fk"
```

Re-check `alembic heads` for the current head (should now be Task 1's new migration) and confirm the generated file's `down_revision` points to it. Fill in:

```python
def upgrade() -> None:
    bind = op.get_bind()

    # 1. Add the new FK column, nullable for now so we can backfill it.
    op.add_column(
        "range_events",
        sa.Column("range_location_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # 2. One RangeLocation row per distinct existing location string.
    distinct_locations = bind.execute(
        sa.text("SELECT DISTINCT location FROM range_events")
    ).fetchall()
    for (name,) in distinct_locations:
        bind.execute(
            sa.text(
                "INSERT INTO range_locations (id, name) VALUES (gen_random_uuid(), :name)"
            ),
            {"name": name},
        )

    # 3. Point every event at the matching new row.
    bind.execute(
        sa.text(
            "UPDATE range_events SET range_location_id = rl.id "
            "FROM range_locations rl WHERE rl.name = range_events.location"
        )
    )

    # 4. Now safe to make it required and add the FK constraint.
    op.alter_column("range_events", "range_location_id", nullable=False)
    op.create_foreign_key(
        "fk_range_events_range_location_id", "range_events", "range_locations",
        ["range_location_id"], ["id"], ondelete="RESTRICT",
    )

    # 5. Drop the old free-text column.
    op.drop_column("range_events", "location")


def downgrade() -> None:
    bind = op.get_bind()
    op.add_column("range_events", sa.Column("location", sa.Text(), nullable=True))
    bind.execute(
        sa.text(
            "UPDATE range_events SET location = rl.name "
            "FROM range_locations rl WHERE rl.id = range_events.range_location_id"
        )
    )
    op.alter_column("range_events", "location", nullable=False)
    op.drop_constraint("fk_range_events_range_location_id", "range_events", type_="foreignkey")
    op.drop_column("range_events", "range_location_id")
```

Add `from sqlalchemy.dialects import postgresql` to the file's imports if not already present.

- [ ] **Step 4: Update the service**

In `backend/app/services/ranges.py`:

Change `_range_context` (line 62-64) from:

```python
def _range_context(event: RangeEvent, *, reason: str | None = None) -> str:
    context = f"date={event.date.isoformat()} | type={event.range_type.value} | location={event.location}"
    return f"{context} | reason={reason}" if reason else context
```

to (resolve the name via a session lookup, since `event.location` no longer exists):

```python
def _range_context(session: Session, event: RangeEvent, *, reason: str | None = None) -> str:
    from app.db.models import RangeLocation
    loc = session.get(RangeLocation, event.range_location_id)
    location_name = loc.name if loc else str(event.range_location_id)
    context = f"date={event.date.isoformat()} | type={event.range_type.value} | location={location_name}"
    return f"{context} | reason={reason}" if reason else context
```

Update `_range_context`'s two call sites in the same file (inside `_notify_roster_change`, both currently `_range_context(event)` / implicitly via the `f"..."` composing `fill`) to pass `session` as the first argument: `_range_context(session, event)`.

In `create_range_event(...)`, change the `location: str` parameter to `range_location_id: uuid.UUID`, and change the `RangeEvent(...)` construction's `location=location,` to `range_location_id=range_location_id,`. Add a not-found check mirroring the existing `hierarchy_node_id` check right above it:

```python
    if session.get(HierarchyNode, hierarchy_node_id) is None:
        raise RangeValidationError("hierarchy_node_not_found")
    if session.get(RangeLocation, range_location_id) is None:
        raise RangeValidationError("range_location_not_found")
```

(Add `RangeLocation` to the `from app.db.models import (...)` block at the top of the file.)

In `update_range_event(...)`, change the `location: str | object = _UNSET` parameter to `range_location_id: uuid.UUID | object = _UNSET`, and change:

```python
    if location is not _UNSET:
        before["location"] = event.location
        event.location = location
        after["location"] = location
```

to:

```python
    if range_location_id is not _UNSET:
        if session.get(RangeLocation, range_location_id) is None:
            raise RangeValidationError("range_location_not_found")
        before["range_location_id"] = str(event.range_location_id)
        event.range_location_id = range_location_id
        after["range_location_id"] = str(range_location_id)
```

- [ ] **Step 5: Update the routes**

In `backend/app/routes/ranges.py`:

Change `CreateRangeEventBody.location: str = Field(min_length=1)` to `CreateRangeEventBody.range_location_id: uuid.UUID`.

Change `UpdateRangeEventBody.location: str | None = None` to `UpdateRangeEventBody.range_location_id: uuid.UUID | None = None`.

Change `RangeEventOut`'s `location: str` field to two fields:

```python
    range_location_id: uuid.UUID
    location: str
```

In `_event_out(...)`, resolve the location name via the FK before building the response — add near the top of the function body (after `node = _event_node(session, event)`):

```python
    from app.db.models import RangeLocation
    location = session.get(RangeLocation, event.range_location_id)
    location_name = location.name if location else ""
```

and change the `RangeEventOut(...)` construction's `location=event.location,` to:

```python
        range_location_id=event.range_location_id,
        location=location_name,
```

In `create_range_event(...)` (the route), change `location=body.location,` to `range_location_id=body.range_location_id,` in the `svc.create_range_event(...)` call.

The `update_range_event` route already forwards `**updates` from `body.model_dump(exclude_unset=True, ...)`, so no change is needed there beyond the schema field rename above (the dict key will now be `range_location_id`, matching the service's renamed parameter).

- [ ] **Step 6: Update every backend test that constructs a `RangeEvent`/calls `create_range_event`/`update_range_event`/posts to `/api/ranges`**

The mechanical rule for every hit below: replace `location="<name>"` with `range_location_id=create_range_location(<session-var>, name="<name>").id` when calling a Python function (`create_range_event`/`update_range_event`/`RangeEvent(...)`), or replace the JSON key `"location": "<name>"` with `"range_location_id": str(create_range_location(<session-var>, name="<name>").id)` when building an HTTP request body in an integration test. Add `create_range_location` to each file's existing `from tests.helpers import (...)` line.

Apply this to the shared per-file helpers first (highest leverage — fixing these fixes most of each file's tests in one edit):

- `tests/unit/test_range_reminders.py:20-33` (`_setup` helper) — replace `location="range",` with `range_location_id=create_range_location(session, name="range").id,`. Add `create_range_location` to the `from tests.helpers import ...` import.
- `tests/unit/test_range_lifecycle_guards.py:19-28` (`_event` helper) — replace `location="מטווח",` with `range_location_id=create_range_location(session, name="מטווח").id,`.
- `tests/unit/test_range_candidates.py:27-36` (`_event` helper) — replace `location="range",` with `range_location_id=create_range_location(session, name="range").id,`.
- `tests/unit/test_range_excusal.py:12-21` (`_assignment` helper) — replace `location="range",` with `range_location_id=create_range_location(session, name="range").id,`.
- `tests/unit/test_range_batch_assign.py:13-22` (`_event` helper) — replace `location="range",` with `range_location_id=create_range_location(session, name="range").id,`.
- `tests/unit/test_range_attendance.py:30-44` (`_setup_event_and_assignment` helper) — replace `location="מטווח",` with `range_location_id=create_range_location(session, name="מטווח").id,`.

Then apply the same rule to every remaining direct (non-helper) call site in these files — grep each file for `location=` (Python) or `"location":` (JSON) after the helper edits above and convert every remaining hit; these are the calls not routed through a shared helper:

- `tests/unit/test_ranges_service.py` — every `create_range_event(...)`/`update_range_event(...)` call in the file passes `location=` directly (no shared helper here); also update the two assertions `updated.location == "מטווח חדש"` → `updated.range_location_id == <the new location's id>` and `entry.before.get("location")`/`entry.after.get("location")` → `entry.before.get("range_location_id")`/`entry.after.get("range_location_id")` (compared as `str(...)` per the service's audit-trail convention from Step 4).
- `tests/unit/test_range_models.py` — 5 direct `RangeEvent(...)` constructions; each needs its `location="..."` replaced with `range_location_id=create_range_location(session, name="...").id`.
- `tests/unit/test_range_attendance.py` — 2 direct `create_range_event(...)` calls outside the shared helper (`event_a`/`event_b` in the "orders by date" style test, and one more using a `past_date`).
- `tests/integration/test_ranges_api.py` — ~14 JSON-body `"location": "<value>"` hits and 2 places that read the field back from the response (`[e["location"] for e in response.json()]`) — those response-reading assertions are unaffected (the response still has a `location` field, now server-resolved, so no change needed there; only the **request body** keys need to change from `"location"` to `"range_location_id"`).
- `tests/integration/test_range_lifecycle_api.py` — 2 JSON-body hits (one create, one patch).
- `tests/integration/test_range_assignment_reasons.py` — 3 JSON-body hits (3 separate event creations).

For integration tests (raw JSON `client.post`/`client.patch`), create the `RangeLocation` directly via the test's existing `admin_session` fixture before building the request body, e.g.:

```python
loc = create_range_location(admin_session, name="מטווח")
response = client.post(
    "/api/ranges",
    json={"hierarchy_node_id": str(node.id), "range_type": "laser", "date": "2026-10-01",
          "range_location_id": str(loc.id), "required_count": 2},
    headers=auth_headers(dm),
)
```

- [ ] **Step 7: Run the full ranges test suite to verify everything passes**

Run: `pytest -m duty -q -k range` (or, if that marker doesn't cleanly select these files, run each file directly: `pytest backend/tests/unit/test_ranges_service.py backend/tests/unit/test_range_reminders.py backend/tests/unit/test_range_models.py backend/tests/unit/test_range_lifecycle_guards.py backend/tests/unit/test_range_candidates.py backend/tests/unit/test_range_excusal.py backend/tests/unit/test_range_batch_assign.py backend/tests/unit/test_range_attendance.py backend/tests/integration/test_ranges_api.py backend/tests/integration/test_range_lifecycle_api.py backend/tests/integration/test_range_assignment_reasons.py backend/tests/integration/test_range_locations_api.py backend/app/services/tests/test_range_locations.py -v`)
Expected: all PASS. Also grep the whole `backend/` tree for any remaining `\.location\b` reference to `RangeEvent`/`event.location` outside of `_event_out`'s local `location_name` variable, to catch anything the file list above missed: `grep -rn "event\.location\|\.location =" backend/app backend/tests | grep -v duty_location`.

- [ ] **Step 8: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/*_migrate_range_event_location_to_fk.py backend/app/services/ranges.py backend/app/routes/ranges.py backend/tests/helpers.py backend/tests/unit/test_range*.py backend/tests/integration/test_range*.py
git commit -m "feat: migrate RangeEvent.location from free text to range_location_id FK"
```

---

## Task 4: Update `seed.py` to create `RangeLocation` rows

**Files:**
- Modify: `backend/app/scripts/seed.py`

**Interfaces:**
- Consumes: `RangeLocation` (Task 1), `range_location_id` param on `RangeEvent` (Task 3).

- [ ] **Step 1: Add `RangeLocation` to imports and the clear-block delete order**

In `backend/app/scripts/seed.py`, add `RangeLocation,` to the `from app.db.models import (...)` block, right after `RangeExcusalRequest,` (line 48).

In the `if clear:` block, add a delete for `range_locations` right after the existing `session.query(RangeEvent).delete()` (line 83) — it must come after `RangeEvent` is deleted, since `range_events.range_location_id` has `ondelete="RESTRICT"`:

```python
            session.query(RangeEvent).delete()
            session.query(RangeLocation).delete()
```

- [ ] **Step 2: Create `RangeLocation` rows before the 3 `RangeEvent` rows**

Immediately before the `if len(range_soldiers) >= 4:` block (line 1588), add:

```python
            range_locations = {
                name: RangeLocation(name=name)
                for name in ("מטווח דרום", "מטווח חי - שדה האש הצפוני", "שטח אימונים - אלל")
            }
            for loc in range_locations.values():
                session.add(loc)
            session.flush()
```

- [ ] **Step 3: Point each `RangeEvent` at its `RangeLocation`**

Replace each of the 3 events' `location="..."` with the matching `range_location_id=...`:

`past_event` (line ~1595): `location="מטווח דרום",` → `range_location_id=range_locations["מטווח דרום"].id,`

`upcoming_event` (line ~1633): `location="מטווח חי - שדה האש הצפוני",` → `range_location_id=range_locations["מטווח חי - שדה האש הצפוני"].id,`

`far_event` (line ~1655): `location="שטח אימונים - אלל",` → `range_location_id=range_locations["שטח אימונים - אלל"].id,`

- [ ] **Step 4: Verify by running the seed script against a real (or throwaway) database**

If a local dev DB is available (`.\dev.ps1` running), run: `python -m app.scripts.seed --force` from `backend/` (check the script's actual CLI entrypoint/flag name in `backend/app/scripts/seed.py`'s `if __name__ == "__main__":` block first — `seed_module.seed(force=True)` is called directly in `test_enlisted_keva_soldier_is_eligible_for_at_least_one_seeded_duty_type`, confirming a `force` kwarg exists). Confirm it completes without error and that 3 range events + 3 range locations now exist.

If no DB is available in this environment, skip live verification and rely on Task 3's `test_enlisted_keva_soldier_is_eligible_for_at_least_one_seeded_duty_type`-style coverage (that existing test already calls `seed_module.seed(force=True)` against a real test DB) — run it to confirm the seed script itself doesn't crash:

Run: `pytest backend/app/services/tests/test_eligibility.py -k seeded_duty_type -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/scripts/seed.py
git commit -m "feat: create RangeLocation rows in seed script"
```

---

## Task 5: Frontend `rangeLocations` API + query key

**Files:**
- Create: `frontend/src/api/rangeLocations.ts`
- Modify: `frontend/src/queryKeys.ts`

**Interfaces:**
- Produces: `RangeLocation` type, `listRangeLocations(): Promise<RangeLocation[]>`, `createRangeLocation(input: {name: string}): Promise<RangeLocation>`. `queryKeys.rangeLocations()`.

- [ ] **Step 1: Create the API wrapper**

Create `frontend/src/api/rangeLocations.ts` (mirrors `frontend/src/api/dutyConfig.ts:32-37,106-114`):

```ts
import { api } from "./client";

export interface RangeLocation {
  id: string;
  name: string;
  active: boolean;
}

export async function listRangeLocations(): Promise<RangeLocation[]> {
  return (await api.get<RangeLocation[]>("/range-locations")).data;
}

export async function createRangeLocation(input: { name: string }): Promise<RangeLocation> {
  return (await api.post<RangeLocation>("/range-locations", input)).data;
}
```

- [ ] **Step 2: Add the query key**

In `frontend/src/queryKeys.ts`, add alongside the existing `ranges`/`rangeEvent`/`rangeExcusalRequests` entries (lines 88-90):

```ts
  rangeLocations: () => ["rangeLocations"] as const,
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/rangeLocations.ts frontend/src/queryKeys.ts
git commit -m "feat: add rangeLocations API wrapper and query key"
```

---

## Task 6: Update `frontend/src/api/ranges.ts` types

**Files:**
- Modify: `frontend/src/api/ranges.ts`

**Interfaces:**
- Produces: `RangeEvent.range_location_id: string` (new field, `location: string` kept as-is for display). `CreateRangeEventBody.range_location_id: string` (replaces `location`). `UpdateRangeEventBody.range_location_id?: string` (replaces `location`).

- [ ] **Step 1: Update the types**

In `frontend/src/api/ranges.ts`, change:

```ts
export interface RangeEvent { id:string; hierarchy_node_id:string; range_type:RangeType; date:string; location:string; required_count:number; reserve_count:number; status:RangeEventStatus; assignments:RangeAssignment[]; start_time?:string|null; end_time?:string|null; arrival_instructions?:string|null; contact_name?:string|null; contact_phone?:string|null; notes?:string|null; cancellation_reason?:string|null; primary_filled?:number; reserve_filled?:number; assigned_to_me?:boolean; can_edit_attendance?:boolean; }
export interface CreateRangeEventBody { hierarchy_node_id:string; range_type:RangeType; date:string; location:string; required_count:number; reserve_count?:number; start_time?:string|null; end_time?:string|null; arrival_instructions?:string|null; contact_name?:string|null; contact_phone?:string|null; notes?:string|null; }
export interface UpdateRangeEventBody { hierarchy_node_id?:string; range_type?:RangeType; date?:string; start_time?:string|null; end_time?:string|null; location?:string; required_count?:number; reserve_count?:number; arrival_instructions?:string|null; contact_name?:string|null; contact_phone?:string|null; notes?:string|null; force_schedule_change?:boolean; cancel?:boolean; cancellation_reason?:string; }
```

to:

```ts
export interface RangeEvent { id:string; hierarchy_node_id:string; range_type:RangeType; date:string; range_location_id:string; location:string; required_count:number; reserve_count:number; status:RangeEventStatus; assignments:RangeAssignment[]; start_time?:string|null; end_time?:string|null; arrival_instructions?:string|null; contact_name?:string|null; contact_phone?:string|null; notes?:string|null; cancellation_reason?:string|null; primary_filled?:number; reserve_filled?:number; assigned_to_me?:boolean; can_edit_attendance?:boolean; }
export interface CreateRangeEventBody { hierarchy_node_id:string; range_type:RangeType; date:string; range_location_id:string; required_count:number; reserve_count?:number; start_time?:string|null; end_time?:string|null; arrival_instructions?:string|null; contact_name?:string|null; contact_phone?:string|null; notes?:string|null; }
export interface UpdateRangeEventBody { hierarchy_node_id?:string; range_type?:RangeType; date?:string; start_time?:string|null; end_time?:string|null; range_location_id?:string; required_count?:number; reserve_count?:number; arrival_instructions?:string|null; contact_name?:string|null; contact_phone?:string|null; notes?:string|null; force_schedule_change?:boolean; cancel?:boolean; cancellation_reason?:string; }
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/ranges.ts
git commit -m "feat: replace RangeEvent location string with range_location_id in frontend types"
```

---

## Task 7: `RangeFormModal.tsx` — Combobox + inline add-new location

**Files:**
- Modify: `frontend/src/components/ranges/RangeFormModal.tsx`

**Interfaces:**
- Consumes: `RangeLocation`, `createRangeLocation` from `../../api/rangeLocations` (Task 5); `Combobox` from `../Combobox` (existing).
- Produces: `RangeFormModal` gains a required `locations: RangeLocation[]` prop (mirroring `ShiftFormModal`'s `locations` prop).

- [ ] **Step 1: Update imports and props**

In `frontend/src/components/ranges/RangeFormModal.tsx`, change:

```tsx
import { FormEvent, useEffect, useState } from "react";
import { EventDetailModal } from "../planning";
import { CreateRangeEventBody, RangeEvent, RangeType, UpdateRangeEventBody } from "../../api/ranges";
import { RANGE_TYPE_LABELS } from "../../utils/rangeLabels";

interface Props { open: boolean; event?: RangeEvent | null; hierarchyNodeId: string; onClose: () => void; onSubmit: (body: CreateRangeEventBody | UpdateRangeEventBody) => Promise<void>; }
export default function RangeFormModal({ open, event, hierarchyNodeId, onClose, onSubmit }: Props) {
  const [form, setForm] = useState({ range_type: "laser" as RangeType, date: "", start_time: "", end_time: "", location: "", arrival_instructions: "", contact_name: "", contact_phone: "", required_count: 0, reserve_count: 0, notes: "" });
  const [force, setForce] = useState(false); const [error, setError] = useState(""); const [pending, setPending] = useState(false);
  useEffect(() => { if (open) { setForce(false); setError(""); setForm({ range_type: event?.range_type ?? "laser", date: event?.date ?? "", start_time: event?.start_time ?? "", end_time: event?.end_time ?? "", location: event?.location ?? "", arrival_instructions: event?.arrival_instructions ?? "", contact_name: event?.contact_name ?? "", contact_phone: event?.contact_phone ?? "", required_count: event?.required_count ?? 0, reserve_count: event?.reserve_count ?? 0, notes: event?.notes ?? "" }); } }, [open, event]);
```

to:

```tsx
import { FormEvent, useEffect, useState } from "react";
import { EventDetailModal } from "../planning";
import { CreateRangeEventBody, RangeEvent, RangeType, UpdateRangeEventBody } from "../../api/ranges";
import { RangeLocation, createRangeLocation } from "../../api/rangeLocations";
import { RANGE_TYPE_LABELS } from "../../utils/rangeLabels";
import Combobox from "../Combobox";

interface Props { open: boolean; event?: RangeEvent | null; hierarchyNodeId: string; locations: RangeLocation[]; onClose: () => void; onSubmit: (body: CreateRangeEventBody | UpdateRangeEventBody) => Promise<void>; }
export default function RangeFormModal({ open, event, hierarchyNodeId, locations: initialLocations, onClose, onSubmit }: Props) {
  const [locations, setLocations] = useState<RangeLocation[]>(initialLocations);
  const [addingLocation, setAddingLocation] = useState(false);
  const [newLocName, setNewLocName] = useState("");
  const [locSaving, setLocSaving] = useState(false);
  const [form, setForm] = useState({ range_type: "laser" as RangeType, date: "", start_time: "", end_time: "", range_location_id: "", arrival_instructions: "", contact_name: "", contact_phone: "", required_count: 0, reserve_count: 0, notes: "" });
  const [force, setForce] = useState(false); const [error, setError] = useState(""); const [pending, setPending] = useState(false);
  useEffect(() => { if (open) { setForce(false); setError(""); setAddingLocation(false); setNewLocName(""); setForm({ range_type: event?.range_type ?? "laser", date: event?.date ?? "", start_time: event?.start_time ?? "", end_time: event?.end_time ?? "", range_location_id: event?.range_location_id ?? "", arrival_instructions: event?.arrival_instructions ?? "", contact_name: event?.contact_name ?? "", contact_phone: event?.contact_phone ?? "", required_count: event?.required_count ?? 0, reserve_count: event?.reserve_count ?? 0, notes: event?.notes ?? "" }); } }, [open, event]);
  async function handleAddLocation(e: FormEvent) {
    e.preventDefault();
    if (!newLocName.trim()) return;
    setLocSaving(true);
    try {
      const created = await createRangeLocation({ name: newLocName.trim() });
      setLocations(prev => [...prev, created]);
      set("range_location_id", created.id);
      setNewLocName("");
      setAddingLocation(false);
    } finally {
      setLocSaving(false);
    }
  }
```

(`handleAddLocation` mirrors `ShiftFormModal.tsx:219-232`'s `handleAddLocation`, and must be defined after the `set` function below since it calls `set(...)` — adjust definition order accordingly, or reference `setForm` directly instead of `set` if ordering makes `set` unavailable yet: `setForm(prev => ({ ...prev, range_location_id: created.id }))`.)

- [ ] **Step 2: Remove "location" from the generic `fields` array; add a dedicated Combobox block**

Change:

```tsx
  const fields: Array<[string,string,"text"|"date"|"time"|"number"]> = [["date","תאריך","date"],["start_time","התחלה","time"],["end_time","סיום","time"],["location","מיקום","text"],["required_count","ראשיים","number"],["reserve_count","רזרבה","number"],["contact_name","איש קשר","text"],["contact_phone","טלפון","text"]];
```

to (7 entries instead of 8, `location` removed):

```tsx
  const fields: Array<[string,string,"text"|"date"|"time"|"number"]> = [["date","תאריך","date"],["start_time","התחלה","time"],["end_time","סיום","time"],["required_count","ראשיים","number"],["reserve_count","רזרבה","number"],["contact_name","איש קשר","text"],["contact_phone","טלפון","text"]];
```

Change the schedule section's rendering (which used `fields.slice(0, 6)` to grab the first 6 entries including location) from:

```tsx
      <section data-testid="range-form-section-schedule" className="space-y-3">
        <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-200">פרטי זמן ומיקום</h4>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="block text-sm sm:col-span-2">סוג<select data-testid={event ? "edit-range-type" : "new-range-type"} value={form.range_type} onChange={e=>set("range_type",e.target.value)} className={inputClass}><option value="laser">{RANGE_TYPE_LABELS.laser}</option><option value="live">{RANGE_TYPE_LABELS.live}</option><option value="alal">{RANGE_TYPE_LABELS.alal}</option></select></label>
          {fields.slice(0, 6).map(([key,label,type])=><label key={key} className="block text-sm">{label}<input id={`${event ? "edit" : "new"}-${key.replace("_", "-")}`} data-testid={`${event ? "edit" : "new"}-${key.replace("_", "-")}`} type={type} value={form[key as keyof typeof form] as string|number} min={type === "number" ? 0 : undefined} onChange={e=>set(key,type === "number" ? Number(e.target.value) : e.target.value)} className={inputClass} /></label>)}
        </div>
      </section>
```

to (5 generic fields now — date/start_time/end_time/required_count/reserve_count — plus a hand-coded location block mirroring `ShiftFormModal.tsx:312-342`):

```tsx
      <section data-testid="range-form-section-schedule" className="space-y-3">
        <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-200">פרטי זמן ומיקום</h4>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="block text-sm sm:col-span-2">סוג<select data-testid={event ? "edit-range-type" : "new-range-type"} value={form.range_type} onChange={e=>set("range_type",e.target.value)} className={inputClass}><option value="laser">{RANGE_TYPE_LABELS.laser}</option><option value="live">{RANGE_TYPE_LABELS.live}</option><option value="alal">{RANGE_TYPE_LABELS.alal}</option></select></label>
          <div className="block text-sm sm:col-span-2">
            <div className="flex items-center justify-between mb-1">
              <span>מיקום</span>
              {!addingLocation && (
                <button type="button" onClick={() => setAddingLocation(true)} className="text-xs text-blue-600 dark:text-blue-400 hover:underline">
                  + הוסף מיקום
                </button>
              )}
            </div>
            {addingLocation ? (
              <form onSubmit={handleAddLocation} className="flex gap-1">
                <input
                  autoFocus
                  type="text"
                  value={newLocName}
                  onChange={e => setNewLocName(e.target.value)}
                  placeholder="שם המיקום"
                  className={inputClass}
                />
                <button type="submit" disabled={locSaving || !newLocName.trim()} className="px-2 py-1 text-xs bg-blue-600 text-white rounded disabled:opacity-50">
                  שמור
                </button>
                <button type="button" onClick={() => { setAddingLocation(false); setNewLocName(""); }} className="px-2 py-1 text-xs border dark:border-gray-600 dark:text-gray-300 rounded">
                  בטל
                </button>
              </form>
            ) : (
              <Combobox
                testId={event ? "edit-range-location" : "new-range-location"}
                items={locations.map(l => ({ id: l.id, name: l.name }))}
                value={form.range_location_id}
                onChange={v => set("range_location_id", v)}
                placeholder="בחר מיקום"
              />
            )}
          </div>
          {fields.slice(0, 5).map(([key,label,type])=><label key={key} className="block text-sm">{label}<input id={`${event ? "edit" : "new"}-${key.replace("_", "-")}`} data-testid={`${event ? "edit" : "new"}-${key.replace("_", "-")}`} type={type} value={form[key as keyof typeof form] as string|number} min={type === "number" ? 0 : undefined} onChange={e=>set(key,type === "number" ? Number(e.target.value) : e.target.value)} className={inputClass} /></label>)}
        </div>
      </section>
```

The second field-rendering section (contact name/phone, currently `fields.slice(6)`) must change to `fields.slice(5)` since the array shrank by one entry — change:

```tsx
      <section data-testid="range-form-section-contact" className="space-y-3 border-t pt-4">
        <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-200">פרטי קשר</h4>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{fields.slice(6).map(([key,label,type])=>
```

to:

```tsx
      <section data-testid="range-form-section-contact" className="space-y-3 border-t pt-4">
        <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-200">פרטי קשר</h4>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{fields.slice(5).map(([key,label,type])=>
```

- [ ] **Step 3: Verify the submit body**

`submit(e)` spreads `...form` (both create and update branches, e.g. `{ hierarchy_node_id: hierarchyNodeId, ...form, ... }`), so no change is needed there — `form.range_location_id` now flows through under the correct key automatically, matching `CreateRangeEventBody`/`UpdateRangeEventBody`'s renamed field from Task 6.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ranges/RangeFormModal.tsx
git commit -m "feat: replace RangeFormModal free-text location with Combobox + inline add-new"
```

---

## Task 8: `RangePlanningTable.tsx` — location link becomes plain text

**Files:**
- Modify: `frontend/src/components/ranges/RangePlanningTable.tsx`

- [ ] **Step 1: Replace the button with a span**

In `frontend/src/components/ranges/RangePlanningTable.tsx`, change:

```tsx
{key:"location",label:"מיקום",render:e=><button type="button" aria-label={e.location} onClick={()=>onRowClick(e)} className="text-blue-600 dark:text-blue-400 underline hover:text-blue-800 dark:hover:text-blue-300 text-right">{e.location}</button>}
```

to:

```tsx
{key:"location",label:"מיקום",render:e=><span>{e.location}</span>}
```

(The row itself is already clickable via `<PlanningTable ... onRowClick={onRowClick} ...>` at the end of the same expression — dropping the button here doesn't remove any functionality, it only removes the redundant nested clickable element that duplicated the row click.)

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/ranges/RangePlanningTable.tsx
git commit -m "fix: drop redundant location button in favor of plain text (row click still works)"
```

---

## Task 9: `RangesPage.tsx` — fetch and pass `locations` to `RangeFormModal`, fix `save()`

**Files:**
- Modify: `frontend/src/pages/RangesPage.tsx`

**Interfaces:**
- Consumes: `listRangeLocations` (Task 5), `queryKeys.rangeLocations()` (Task 5).

- [ ] **Step 1: Add the query**

In `frontend/src/pages/RangesPage.tsx`, add the import:

```tsx
import { listRangeLocations } from "../api/rangeLocations";
```

Add the query alongside the existing `ranges`/`event`/`excusal`/`soldiers` queries (after line 43's `soldiers` query):

```tsx
  const rangeLocations = useQuery({ queryKey: queryKeys.rangeLocations(), queryFn: listRangeLocations });
```

- [ ] **Step 2: Fix `save()` to use `range_location_id`**

Change:

```tsx
      const createBody = body as CreateRangeEventBody;
      await create({ hierarchy_node_id: createBody.hierarchy_node_id, range_type: createBody.range_type, date: createBody.date, location: createBody.location, start_time: createBody.start_time, end_time: createBody.end_time, arrival_instructions: createBody.arrival_instructions, contact_name: createBody.contact_name, contact_phone: createBody.contact_phone, notes: createBody.notes, required_count: Number(createBody.required_count), reserve_count: Number(createBody.reserve_count) });
```

to:

```tsx
      const createBody = body as CreateRangeEventBody;
      await create({ hierarchy_node_id: createBody.hierarchy_node_id, range_type: createBody.range_type, date: createBody.date, range_location_id: createBody.range_location_id, start_time: createBody.start_time, end_time: createBody.end_time, arrival_instructions: createBody.arrival_instructions, contact_name: createBody.contact_name, contact_phone: createBody.contact_phone, notes: createBody.notes, required_count: Number(createBody.required_count), reserve_count: Number(createBody.reserve_count) });
```

- [ ] **Step 3: Pass `locations` to `RangeFormModal`**

Change:

```tsx
    <RangeFormModal open={formEvent !== undefined} event={formEvent} hierarchyNodeId={nodeId ?? ""} onClose={() => setFormEvent(undefined)} onSubmit={save} />
```

to:

```tsx
    <RangeFormModal open={formEvent !== undefined} event={formEvent} hierarchyNodeId={nodeId ?? ""} locations={rangeLocations.data ?? []} onClose={() => setFormEvent(undefined)} onSubmit={save} />
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/RangesPage.tsx
git commit -m "feat: wire range-locations query into RangesPage and RangeFormModal"
```

---

## Task 10: Update `RangesPage.test.tsx` create-event test for the Combobox flow

**Files:**
- Modify: `frontend/src/pages/RangesPage.test.tsx`

**Interfaces:**
- Consumes: `listRangeLocations` (Task 5, mocked).

- [ ] **Step 1: Mock the new API module**

At the top of `frontend/src/pages/RangesPage.test.tsx`, add:

```tsx
import * as rangeLocationsApi from "../api/rangeLocations";
vi.mock("../api/rangeLocations");
```

In the `beforeEach(...)` block, add a default mock so every test that doesn't override it still renders a usable (empty) Combobox:

```tsx
  vi.mocked(rangeLocationsApi.listRangeLocations).mockResolvedValue([]);
```

- [ ] **Step 2: Update the create-event test**

In the `"creates a new range event via the create form"` test (currently around line 311-355), before `renderWithQuery(<RangesPage />);`, add a mocked existing location and select it via the Combobox instead of typing into a plain text input:

```tsx
    vi.mocked(rangeLocationsApi.listRangeLocations).mockResolvedValue([
      { id: "loc-1", name: "מטווח צפון", active: true },
    ]);
```

Replace:

```tsx
    fireEvent.change(screen.getByTestId("new-location"), { target: { value: "מטווח צפון" } });
```

with (Combobox interaction: focus the input to open the dropdown, then click the matching option — mirrors how `Combobox.test.tsx` exercises selection):

```tsx
    fireEvent.focus(screen.getByTestId("new-range-location"));
    fireEvent.click(await screen.findByText("מטווח צפון"));
```

Update the assertion:

```tsx
    await waitFor(() =>
      expect(rangesApi.createRangeEvent).toHaveBeenCalledWith({
        hierarchy_node_id: "node-1",
        range_type: "live",
        date: "2026-10-01",
        location: "מטווח צפון",
        start_time: "08:00",
        end_time: "12:00",
        arrival_instructions: "להגיע בשמונה",
        contact_name: "אחראי מטווח",
        contact_phone: "050-0000000",
        notes: "ציוד אישי",
        required_count: 6,
        reserve_count: 2,
      }),
    );
```

to:

```tsx
    await waitFor(() =>
      expect(rangesApi.createRangeEvent).toHaveBeenCalledWith({
        hierarchy_node_id: "node-1",
        range_type: "live",
        date: "2026-10-01",
        range_location_id: "loc-1",
        start_time: "08:00",
        end_time: "12:00",
        arrival_instructions: "להגיע בשמונה",
        contact_name: "אחראי מטווח",
        contact_phone: "050-0000000",
        notes: "ציוד אישי",
        required_count: 6,
        reserve_count: 2,
      }),
    );
```

Every other `location: "..."` in this file (in mocked `RangeEvent` read-side fixtures returned from `getRanges`/`getRangeEvent`) needs **no change** — `RangeEvent.location` remains a real string field per Task 6.

- [ ] **Step 3: Run the test**

Run (from `frontend/`): `npm test -- RangesPage.test.tsx`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/RangesPage.test.tsx
git commit -m "test: update RangesPage create-event test for location Combobox"
```

---

## Task 11: Full-suite verification

- [ ] **Step 1: Run the full backend test suite**

Run: `pytest -q` (fast suite; the project's full `--slow` suite is only required before a release per `CLAUDE.md`)
Expected: all PASS

- [ ] **Step 2: Run frontend tests, lint, and typecheck**

Run (from `frontend/`):

```bash
npm test
npm run lint
npm run typecheck
```

Expected: all PASS, zero lint warnings, zero type errors.

- [ ] **Step 3: Manual verification in the browser**

Run `.\dev.ps1`, open `http://localhost:5173/ranges` as a duty manager:
1. Click "מטווח חדש", confirm the מיקום field is a searchable Combobox, not a free-text input.
2. Type a name that doesn't exist yet, confirm "+ הוסף מיקום" lets you create it inline and it becomes selected.
3. Save the event, confirm it appears in the table with the location shown as plain (non-underlined, non-clickable-looking) text, and that clicking anywhere in the row still opens the detail modal.
4. Open the detail modal and the "עריכת שיבוצים" modal, confirm both still show the correct location name in their title/subtitle.
5. Edit the event and confirm the existing location is preselected in the Combobox.

- [ ] **Step 4: Commit if any fixups were needed**

If any step above required fixes, commit them separately with a clear message.
