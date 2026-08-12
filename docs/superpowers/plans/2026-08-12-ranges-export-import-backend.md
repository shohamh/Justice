# Ranges Export/Import — Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add five ranges sheets (`range_locations`, `range_events`, `range_assignments`, `soldier_range_qualifications`, `range_excusal_requests`) to the existing bulk import-session pipeline and the existing three export routers, so range data can be bulk-exported and re-imported through the same review/confirm workflow already used for soldiers/duty shifts/assignments.

**Architecture:** Follows the codebase's existing three-way export split precisely: `range_locations` is config-like data (exported via `/config/export`, like `duty_locations`); `range_events`/`range_assignments` are operational schedule data (exported via `/import/export`'s `EXPORT_DATA_SHEETS`, like `duty_shifts`/`assignments`); `soldier_range_qualifications`/`range_excusal_requests` are approval-workflow data (exported via `/approvals/export`, like `soldier_exemptions`/`exemption_requests`). All five are importable through the single session pipeline (`app/services/import_parsers/v1_standard.py` → `app/services/import_sessions.py` / `app/services/import_approvals.py` → `confirm_session`).

**Tech Stack:** Python, FastAPI, SQLAlchemy, Pydantic, openpyxl, pytest.

## Global Constraints

- Every new resolver/apply block must follow the exact per-row dict shape and nested-`SAVEPOINT` isolation already used by neighboring resolvers/apply blocks in `import_sessions.py` (see `_resolve_duty_shifts`/`_resolve_assignments` and their apply blocks) — one row's failure must not poison the rest of the batch.
- Import never re-triggers live business-logic side effects (notifications, cascading deletes, capacity locks). Applying an imported row is always a direct field write, matching how `exemption_requests`/`personal_constraints` import today does **not** call the live approval endpoints.
- `range_events`/`range_assignments` are always-"new" on import (no dedup against existing rows), matching the existing `duty_shifts`/`assignments` convention exactly.
- `range_locations`, `soldier_range_qualifications`, and `range_excusal_requests` are update-by-key (`name` for locations, `id` for the other two), matching `duty_locations`/`soldier_exemptions`/`exemption_requests`.
- All new resolvers/routes reuse `require_duty_manager_or_admin` and `is_node_in_actor_scope` for authorization/scoping, exactly as `duty_shifts`/`assignments` do today.
- `RangeType` values: `laser`, `live`, `alal`. `RangeEventStatus`: `planned`, `completed`, `cancelled`. `RangeAttendanceStatus`: `pending`, `present`, `no_show`. `RangeExcusalStatus`: `pending`, `approved`, `rejected`. (`app/db/models.py:175`, `:821`, `:827`, `:833`.)

---

## File Structure

- Modify `backend/app/services/import_parsers/schema.py` — add 5 `Import*Row` models + fields on `ParsedImportData`.
- Modify `backend/app/services/import_parsers/v1_standard.py` — add 5 sheets to `KNOWN_SHEETS` + 5 parse blocks.
- Modify `backend/app/services/import_sessions.py` — add `_resolve_range_locations`, `_resolve_range_events`, `_resolve_range_assignments` + wire into `_resolve_and_score`; add 3 apply blocks to `confirm_session`.
- Modify `backend/app/services/import_approvals.py` — add `resolve_soldier_range_qualifications`, `resolve_range_excusal_requests` + wire into `_resolve_and_score` (in `import_sessions.py`); add 2 apply blocks to `confirm_session`.
- Modify `backend/app/routes/import_sessions.py` — add 5 new counts to `_session_summary`'s `row_summary`.
- Modify `backend/app/routes/config_export.py` — add `range_locations` sheet.
- Modify `backend/app/routes/import_excel.py` — add `range_events`/`range_assignments` to `EXPORT_DATA_SHEETS`; add example rows for all 5 new sheets to `/import/template`.
- Modify `backend/app/routes/approvals_export.py` — add `soldier_range_qualifications`/`range_excusal_requests` sheets.
- Modify `backend/tests/helpers.py` — add `create_range_event`/`create_range_assignment` test factories.
- New/modify test files: `backend/tests/test_import_sessions_resolvers.py`, `backend/app/services/tests/test_import_approvals_service.py`, `backend/app/services/tests/test_import_sessions_service.py`, `backend/app/services/tests/test_import_parser_v1.py`, `backend/tests/integration/test_import_sessions_config_confirm.py`, `backend/tests/integration/test_approvals_export_import_e2e.py`, `backend/tests/integration/test_config_export.py` (or existing equivalent — see Task 7), `backend/tests/integration/test_import_excel_export.py` (or existing equivalent — see Task 8).

---

### Task 1: Schema — new `Import*Row` models

**Files:**
- Modify: `backend/app/services/import_parsers/schema.py`
- Test: `backend/app/services/tests/test_import_parser_v1.py` (schema is exercised indirectly through the parser test in Task 2 — no standalone schema test file exists in this codebase, so this task's tests live in Task 2)

**Interfaces:**
- Produces: `ImportRangeLocationRow`, `ImportRangeEventRow`, `ImportRangeAssignmentRow`, `ImportSoldierRangeQualificationRow`, `ImportRangeExcusalRequestRow` (all `pydantic.BaseModel`), and 5 new list fields on `ParsedImportData`.

- [ ] **Step 1: Add the 5 row models and wire them into `ParsedImportData`**

Add after `ImportAssignmentRow` (after line 121 of `schema.py`):

```python
class ImportRangeLocationRow(BaseModel):
    source_row: int
    name: str
    active: bool | None = None


class ImportRangeEventRow(BaseModel):
    source_row: int
    hierarchy_node_name: str | None = None
    range_type: str
    date: str
    range_location_name: str
    required_count: int
    reserve_count: int = 0
    start_time: str | None = None
    end_time: str | None = None
    arrival_instructions: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    notes: str | None = None
    status: str | None = None


class ImportRangeAssignmentRow(BaseModel):
    source_row: int
    personal_number: str
    full_name: str
    hierarchy_node_name: str | None = None
    range_type: str
    date: str
    range_location_name: str
    is_reserve: bool = False
    is_draft: bool = False
    attendance_status: str | None = None
    note: str | None = None


class ImportSoldierRangeQualificationRow(BaseModel):
    source_row: int
    id: str | None = None
    soldier_personal_number: str
    range_type: str
    valid_until: str


class ImportRangeExcusalRequestRow(BaseModel):
    source_row: int
    id: str | None = None
    soldier_personal_number: str
    requested_by_personal_number: str | None = None
    hierarchy_node_name: str | None = None
    range_type: str
    date: str
    range_location_name: str
    reason: str | None = None
    status: str
    decided_by_personal_number: str | None = None
    decision_note: str | None = None
```

Then add to `ParsedImportData` (after the `assignments` field):

```python
    range_locations: list[ImportRangeLocationRow] = []
    range_events: list[ImportRangeEventRow] = []
    range_assignments: list[ImportRangeAssignmentRow] = []
    soldier_range_qualifications: list[ImportSoldierRangeQualificationRow] = []
    range_excusal_requests: list[ImportRangeExcusalRequestRow] = []
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/import_parsers/schema.py
git commit -m "feat: add range import row schemas"
```

---

### Task 2: Parser — parse the 5 new sheets

**Files:**
- Modify: `backend/app/services/import_parsers/v1_standard.py`
- Test: `backend/app/services/tests/test_import_parser_v1.py`

**Interfaces:**
- Consumes: `ImportRangeLocationRow`, `ImportRangeEventRow`, `ImportRangeAssignmentRow`, `ImportSoldierRangeQualificationRow`, `ImportRangeExcusalRequestRow` (Task 1).
- Produces: `V1StandardParser.parse(wb)` populates `range_locations`, `range_events`, `range_assignments`, `soldier_range_qualifications`, `range_excusal_requests` on the returned `ParsedImportData`.

- [ ] **Step 1: Write the failing test**

Read the top of `backend/app/services/tests/test_import_parser_v1.py` first to match its existing `_wb(...)` helper / workbook-building convention (it builds an `openpyxl.Workbook` with named sheets and header+data rows, then calls `V1StandardParser().parse(wb)`). Add:

```python
def test_parses_range_sheets():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    ws_loc = wb.create_sheet("range_locations")
    ws_loc.append(["name", "active"])
    ws_loc.append(["מטווח דרומי", "true"])

    ws_ev = wb.create_sheet("range_events")
    ws_ev.append([
        "hierarchy_node_name", "range_type", "date", "range_location_name",
        "required_count", "reserve_count", "start_time", "end_time",
        "arrival_instructions", "contact_name", "contact_phone", "notes", "status",
    ])
    ws_ev.append([
        "מדור א", "live", "15.06.2024", "מטווח דרומי",
        "10", "2", "08:00", "12:00", "התייצבות בשער", "דני", "050-1234567", "", "planned",
    ])

    ws_as = wb.create_sheet("range_assignments")
    ws_as.append([
        "personal_number", "full_name", "hierarchy_node_name", "range_type", "date",
        "range_location_name", "is_reserve", "is_draft", "attendance_status", "note",
    ])
    ws_as.append(["12345", "ישראל ישראלי", "מדור א", "live", "15.06.2024", "מטווח דרומי", "false", "false", "pending", ""])

    ws_q = wb.create_sheet("soldier_range_qualifications")
    ws_q.append(["id", "soldier_personal_number", "range_type", "valid_until"])
    ws_q.append(["", "12345", "live", "15.06.2025"])

    ws_ex = wb.create_sheet("range_excusal_requests")
    ws_ex.append([
        "id", "soldier_personal_number", "requested_by_personal_number", "hierarchy_node_name",
        "range_type", "date", "range_location_name", "reason", "status",
        "decided_by_personal_number", "decision_note",
    ])
    ws_ex.append(["", "12345", "12345", "מדור א", "live", "15.06.2024", "מטווח דרומי", "חופשה", "pending", "", ""])

    data = V1StandardParser().parse(wb)

    assert len(data.range_locations) == 1
    assert data.range_locations[0].name == "מטווח דרומי"
    assert data.range_locations[0].active is True

    assert len(data.range_events) == 1
    ev = data.range_events[0]
    assert ev.hierarchy_node_name == "מדור א"
    assert ev.range_type == "live"
    assert ev.date == "2024-06-15"
    assert ev.range_location_name == "מטווח דרומי"
    assert ev.required_count == 10
    assert ev.reserve_count == 2
    assert ev.status == "planned"

    assert len(data.range_assignments) == 1
    assert data.range_assignments[0].personal_number == "12345"
    assert data.range_assignments[0].attendance_status == "pending"

    assert len(data.soldier_range_qualifications) == 1
    assert data.soldier_range_qualifications[0].valid_until == "2025-06-15"

    assert len(data.range_excusal_requests) == 1
    assert data.range_excusal_requests[0].status == "pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/app/services/tests/test_import_parser_v1.py::test_parses_range_sheets -v`
Expected: FAIL (sheets not in `KNOWN_SHEETS`, empty lists returned)

- [ ] **Step 3: Implement the parse blocks**

In `v1_standard.py`, add the 5 sheet names to `KNOWN_SHEETS`:

```python
KNOWN_SHEETS = {
    "soldiers", "duty_shifts", "assignments", "duty_locations", "hierarchy",
    "duty_types", "exemption_types", "shift_templates",
    "swap_requests", "exemption_requests", "soldier_field_updates",
    "soldier_enrollment_requests", "personal_constraints", "soldier_exemptions",
    "system_settings", "bug_reports",
    "range_locations", "range_events", "range_assignments",
    "soldier_range_qualifications", "range_excusal_requests",
}
```

Add these imports to the `from app.services.import_parsers.schema import (...)` block:

```python
    ImportRangeAssignmentRow,
    ImportRangeEventRow,
    ImportRangeExcusalRequestRow,
    ImportRangeLocationRow,
    ImportSoldierRangeQualificationRow,
```

Add parse blocks in `V1StandardParser.parse`, right before the `return ParsedImportData(...)` call:

```python
        range_locations = [
            ImportRangeLocationRow(
                source_row=r["_row"],
                name=str(r.get("name") or "").strip(),
                active=_parse_bool(r.get("active")),
            )
            for r in _sheet_rows(wb, "range_locations")
        ]

        range_events = [
            ImportRangeEventRow(
                source_row=r["_row"],
                hierarchy_node_name=str(r.get("hierarchy_node_name") or "").strip() or None,
                range_type=str(r.get("range_type") or "").strip(),
                date=_parse_date(r.get("date")) or "",
                range_location_name=str(r.get("range_location_name") or "").strip(),
                required_count=int(r.get("required_count") or 1),
                reserve_count=int(r.get("reserve_count") or 0),
                start_time=str(r.get("start_time") or "").strip() or None,
                end_time=str(r.get("end_time") or "").strip() or None,
                arrival_instructions=str(r.get("arrival_instructions") or "").strip() or None,
                contact_name=str(r.get("contact_name") or "").strip() or None,
                contact_phone=str(r.get("contact_phone") or "").strip() or None,
                notes=str(r.get("notes") or "").strip() or None,
                status=str(r.get("status") or "").strip() or None,
            )
            for r in _sheet_rows(wb, "range_events")
        ]

        range_assignments = [
            ImportRangeAssignmentRow(
                source_row=r["_row"],
                personal_number=str(r.get("personal_number") or "").strip(),
                full_name=str(r.get("full_name") or "").strip(),
                hierarchy_node_name=str(r.get("hierarchy_node_name") or "").strip() or None,
                range_type=str(r.get("range_type") or "").strip(),
                date=_parse_date(r.get("date")) or "",
                range_location_name=str(r.get("range_location_name") or "").strip(),
                is_reserve=_parse_bool(r.get("is_reserve")) or False,
                is_draft=_parse_bool(r.get("is_draft")) or False,
                attendance_status=str(r.get("attendance_status") or "").strip() or None,
                note=str(r.get("note") or "").strip() or None,
            )
            for r in _sheet_rows(wb, "range_assignments")
        ]

        soldier_range_qualifications = [
            ImportSoldierRangeQualificationRow(
                source_row=r["_row"],
                id=str(r.get("id") or "").strip() or None,
                soldier_personal_number=str(r.get("soldier_personal_number") or "").strip(),
                range_type=str(r.get("range_type") or "").strip(),
                valid_until=_parse_date(r.get("valid_until")) or "",
            )
            for r in _sheet_rows(wb, "soldier_range_qualifications")
        ]

        range_excusal_requests = [
            ImportRangeExcusalRequestRow(
                source_row=r["_row"],
                id=str(r.get("id") or "").strip() or None,
                soldier_personal_number=str(r.get("soldier_personal_number") or "").strip(),
                requested_by_personal_number=str(r.get("requested_by_personal_number") or "").strip() or None,
                hierarchy_node_name=str(r.get("hierarchy_node_name") or "").strip() or None,
                range_type=str(r.get("range_type") or "").strip(),
                date=_parse_date(r.get("date")) or "",
                range_location_name=str(r.get("range_location_name") or "").strip(),
                reason=str(r.get("reason") or "").strip() or None,
                status=str(r.get("status") or "").strip(),
                decided_by_personal_number=str(r.get("decided_by_personal_number") or "").strip() or None,
                decision_note=str(r.get("decision_note") or "").strip() or None,
            )
            for r in _sheet_rows(wb, "range_excusal_requests")
        ]
```

Then add these 5 to the `return ParsedImportData(...)` call's keyword arguments (alongside `soldiers=soldiers, ...`):

```python
            range_locations=range_locations,
            range_events=range_events,
            range_assignments=range_assignments,
            soldier_range_qualifications=soldier_range_qualifications,
            range_excusal_requests=range_excusal_requests,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/app/services/tests/test_import_parser_v1.py -v`
Expected: PASS (including all pre-existing tests in the file)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/import_parsers/v1_standard.py backend/app/services/tests/test_import_parser_v1.py
git commit -m "feat: parse range sheets in v1_standard import parser"
```

---

### Task 3: Test helpers — `create_range_event` / `create_range_assignment`

**Files:**
- Modify: `backend/tests/helpers.py`

**Interfaces:**
- Produces: `create_range_event(session, *, hierarchy_node, range_location, range_type="live", event_date=None, required_count=5, reserve_count=0, status="planned") -> RangeEvent` and `create_range_assignment(session, *, range_event, soldier, is_reserve=False, attendance_status="pending") -> RangeAssignment`, for use by Tasks 4–8's tests.

- [ ] **Step 1: Add the two factories**

`backend/tests/helpers.py` already imports `RangeLocation` (used by the existing `create_range_location`). Add these imports at the top: `RangeAssignment`, `RangeEvent` from `app.db.models`, and `date` from `datetime`. Then add after `create_range_location`:

```python
def create_range_event(
    session: Session, *, hierarchy_node, range_location, range_type: str = "live",
    event_date: date | None = None, required_count: int = 5, reserve_count: int = 0,
    status: str = "planned",
) -> RangeEvent:
    event = RangeEvent(
        hierarchy_node_id=hierarchy_node.id,
        range_type=range_type,
        date=event_date or date(2024, 6, 15),
        range_location_id=range_location.id,
        required_count=required_count,
        reserve_count=reserve_count,
        status=status,
    )
    session.add(event)
    session.flush()
    return event


def create_range_assignment(
    session: Session, *, range_event: RangeEvent, soldier: Soldier,
    is_reserve: bool = False, attendance_status: str = "pending",
) -> RangeAssignment:
    assignment = RangeAssignment(
        range_event_id=range_event.id, soldier_id=soldier.id,
        is_reserve=is_reserve, attendance_status=attendance_status,
    )
    session.add(assignment)
    session.flush()
    return assignment
```

There is no test to run for this step — it's pure test infrastructure exercised by later tasks.

- [ ] **Step 2: Commit**

```bash
git add backend/tests/helpers.py
git commit -m "test: add range_event/range_assignment test factories"
```

---

### Task 4: Resolvers — `_resolve_range_locations` and `_resolve_range_events`

**Files:**
- Modify: `backend/app/services/import_sessions.py`
- Test: `backend/tests/test_import_sessions_resolvers.py`

**Interfaces:**
- Consumes: `ImportRangeLocationRow`, `ImportRangeEventRow` (Task 1); `create_node`, `create_soldier`, `create_range_location` (existing helpers, Task 3 adds none used here).
- Produces: `_resolve_range_locations(session, data, overrides=None) -> list[dict]` — each dict has keys `row, action, errors, name, active, existing_id`. `_resolve_range_events(session, data, actor, node_by_name=None, node_by_row=None, overrides=None) -> list[dict]` — each dict has keys `row, action, errors, hierarchy_node_name, resolved_hierarchy_node_id, range_type, date, range_location_name, resolved_range_location_id, required_count, reserve_count, start_time, end_time, arrival_instructions, contact_name, contact_phone, notes, status`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_import_sessions_resolvers.py`:

```python
from app.db.models import RangeLocation
from app.services.import_parsers.schema import ImportRangeEventRow, ImportRangeLocationRow
from app.services.import_sessions import _resolve_range_events, _resolve_range_locations
from tests.helpers import create_range_location


def test_resolve_range_locations_new_and_update(app_session):
    existing = create_range_location(app_session, name="מטווח קיים")
    data = ParsedImportData(
        parser_id="v1_standard",
        range_locations=[
            ImportRangeLocationRow(source_row=2, name="מטווח קיים", active=False),
            ImportRangeLocationRow(source_row=3, name="מטווח חדש", active=True),
        ],
    )
    result = _resolve_range_locations(app_session, data)
    assert result[0]["action"] == "update"
    assert result[0]["existing_id"] == str(existing.id)
    assert result[1]["action"] == "new"
    assert result[1]["existing_id"] is None


def test_resolve_range_locations_missing_name_error(app_session):
    data = ParsedImportData(
        parser_id="v1_standard",
        range_locations=[ImportRangeLocationRow(source_row=2, name="", active=True)],
    )
    result = _resolve_range_locations(app_session, data)
    assert result[0]["action"] == "error"


def test_resolve_range_events_new(app_session):
    admin = create_soldier(app_session, personal_number="admin-1", role="admin")
    node = create_node(app_session, name="מדור א", level="group")
    loc = create_range_location(app_session, name="מטווח דרומי")
    data = ParsedImportData(
        parser_id="v1_standard",
        range_events=[
            ImportRangeEventRow(
                source_row=2, hierarchy_node_name="מדור א", range_type="live",
                date="2024-06-15", range_location_name="מטווח דרומי",
                required_count=10, reserve_count=2, status="planned",
            )
        ],
    )
    result = _resolve_range_events(app_session, data, admin)
    row = result[0]
    assert row["action"] == "new"
    assert row["resolved_hierarchy_node_id"] == str(node.id)
    assert row["resolved_range_location_id"] == str(loc.id)
    assert row["required_count"] == 10


def test_resolve_range_events_unknown_location_error(app_session):
    admin = create_soldier(app_session, personal_number="admin-2", role="admin")
    create_node(app_session, name="מדור א", level="group")
    data = ParsedImportData(
        parser_id="v1_standard",
        range_events=[
            ImportRangeEventRow(
                source_row=2, hierarchy_node_name="מדור א", range_type="live",
                date="2024-06-15", range_location_name="לא קיים", required_count=10,
            )
        ],
    )
    result = _resolve_range_events(app_session, data, admin)
    assert result[0]["action"] == "error"
    assert any("מטווח" in e for e in result[0]["errors"])


def test_resolve_range_events_invalid_range_type_error(app_session):
    admin = create_soldier(app_session, personal_number="admin-3", role="admin")
    create_node(app_session, name="מדור א", level="group")
    create_range_location(app_session, name="מטווח דרומי")
    data = ParsedImportData(
        parser_id="v1_standard",
        range_events=[
            ImportRangeEventRow(
                source_row=2, hierarchy_node_name="מדור א", range_type="not_a_type",
                date="2024-06-15", range_location_name="מטווח דרומי", required_count=10,
            )
        ],
    )
    result = _resolve_range_events(app_session, data, admin)
    assert result[0]["action"] == "error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_import_sessions_resolvers.py -k range -v`
Expected: FAIL with `ImportError`/`AttributeError` (functions don't exist yet)

- [ ] **Step 3: Implement `_resolve_range_locations` and `_resolve_range_events`**

Add `RangeEvent, RangeLocation, RangeType, RangeEventStatus` to the `from app.db.models import (...)` block in `import_sessions.py`. Add after `_resolve_duty_locations` (after line 225):

```python
def _resolve_range_locations(
    session: Session,
    data: ParsedImportData,
    overrides: dict[str, dict] | None = None,
) -> list[dict]:
    overrides = overrides or {}
    existing_by_name = {
        loc.name: loc for loc in session.execute(select(RangeLocation)).scalars()
    }
    out = []
    for row in data.range_locations:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        name = field("name", row.name)
        active = field("active", row.active)

        if not name:
            errors.append("חסר שם מיקום מטווח")
        existing = existing_by_name.get(name) if name else None
        action = "error" if errors else ("update" if existing else "new")
        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "name": name,
            "active": active,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def _resolve_range_events(
    session: Session,
    data: ParsedImportData,
    actor: Soldier,
    node_by_name: dict[str, str] | None = None,
    node_by_row: dict[str, str] | None = None,
    overrides: dict[str, dict] | None = None,
) -> list[dict]:
    node_by_name = node_by_name or {}
    node_by_row = node_by_row or {}
    overrides = overrides or {}
    nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}
    locations_by_name = {loc.name: loc for loc in session.execute(select(RangeLocation)).scalars()}

    out = []
    for row in data.range_events:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        hierarchy_node_name = field("hierarchy_node_name", row.hierarchy_node_name)
        range_type = field("range_type", row.range_type)
        event_date = field("date", row.date)
        range_location_name = field("range_location_name", row.range_location_name)
        required_count = field("required_count", row.required_count)
        reserve_count = field("reserve_count", row.reserve_count)
        start_time = field("start_time", row.start_time)
        end_time = field("end_time", row.end_time)
        arrival_instructions = field("arrival_instructions", row.arrival_instructions)
        contact_name = field("contact_name", row.contact_name)
        contact_phone = field("contact_phone", row.contact_phone)
        notes = field("notes", row.notes)
        status = field("status", row.status) or RangeEventStatus.planned.value

        node = None
        if hierarchy_node_name:
            row_key = f"range_events:{row.source_row}"
            mapped_id = node_by_row.get(row_key) or node_by_name.get(hierarchy_node_name)
            if mapped_id:
                try:
                    node = session.get(HierarchyNode, uuid.UUID(mapped_id))
                except ValueError:
                    pass
            if node is None:
                node = nodes_by_name.get(hierarchy_node_name)
        if node is None:
            errors.append(f"יחידה לא מזוהה '{hierarchy_node_name}'")

        location = locations_by_name.get(range_location_name) if range_location_name else None
        if location is None:
            errors.append(f"מיקום מטווח לא מזוהה '{range_location_name}'")

        if range_type not in (rt.value for rt in RangeType):
            errors.append(f"סוג מטווח לא תקין '{range_type}'")
        if not event_date:
            errors.append("חסר תאריך")
        if status not in (s.value for s in RangeEventStatus):
            errors.append(f"סטטוס לא תקין '{status}'")

        action = "error" if errors else "new"

        if action == "new" and node is not None and actor.role != "admin":
            if not is_node_in_actor_scope(session=session, actor=actor, node_id=node.id):
                action = "out_of_scope"

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "hierarchy_node_name": hierarchy_node_name,
            "resolved_hierarchy_node_id": str(node.id) if node is not None else None,
            "range_type": range_type,
            "date": event_date,
            "range_location_name": range_location_name,
            "resolved_range_location_id": str(location.id) if location is not None else None,
            "required_count": required_count,
            "reserve_count": reserve_count,
            "start_time": start_time,
            "end_time": end_time,
            "arrival_instructions": arrival_instructions,
            "contact_name": contact_name,
            "contact_phone": contact_phone,
            "notes": notes,
            "status": status,
        })
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_import_sessions_resolvers.py -v`
Expected: PASS (all tests in the file, including pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/import_sessions.py backend/tests/test_import_sessions_resolvers.py
git commit -m "feat: add range_locations and range_events import resolvers"
```

---

### Task 5: Resolver — `_resolve_range_assignments`

**Files:**
- Modify: `backend/app/services/import_sessions.py`
- Test: `backend/tests/test_import_sessions_resolvers.py`

**Interfaces:**
- Consumes: `ImportRangeAssignmentRow` (Task 1); output rows of `_resolve_range_events` (Task 4) as `resolved_range_events: list[dict]`.
- Produces: `_resolve_range_assignments(session, data, actor, resolved_range_events, overrides=None) -> list[dict]` — each dict has keys `row, action, errors, warnings, personal_number, full_name, range_type, date, range_location_name, is_reserve, is_draft, attendance_status, note, resolved_soldier_id, resolved_range_event_id, matched_session_row`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_import_sessions_resolvers.py`:

```python
from app.services.import_sessions import _resolve_range_assignments
from tests.helpers import create_range_event


def test_resolve_range_assignments_matches_existing_event(app_session):
    admin = create_soldier(app_session, personal_number="admin-4", role="admin")
    node = create_node(app_session, name="מדור א", level="group")
    loc = create_range_location(app_session, name="מטווח דרומי")
    soldier = create_soldier(app_session, personal_number="12345", full_name="ישראל ישראלי", hierarchy_node_id=node.id)
    event = create_range_event(app_session, hierarchy_node=node, range_location=loc)

    data = ParsedImportData(
        parser_id="v1_standard",
        range_assignments=[
            ImportRangeAssignmentRow(
                source_row=2, personal_number="12345", full_name="ישראל ישראלי",
                hierarchy_node_name="מדור א", range_type="live", date="2024-06-15",
                range_location_name="מטווח דרומי",
            )
        ],
    )
    result = _resolve_range_assignments(app_session, data, admin, [])
    row = result[0]
    assert row["action"] == "new"
    assert row["resolved_soldier_id"] == str(soldier.id)
    assert row["resolved_range_event_id"] == str(event.id)


def test_resolve_range_assignments_matches_session_created_event(app_session):
    admin = create_soldier(app_session, personal_number="admin-5", role="admin")
    node = create_node(app_session, name="מדור א", level="group")
    create_range_location(app_session, name="מטווח דרומי")
    create_soldier(app_session, personal_number="12345", full_name="ישראל ישראלי", hierarchy_node_id=node.id)

    resolved_events = [{
        "row": 2, "action": "new", "range_type": "live", "date": "2024-06-15",
        "resolved_hierarchy_node_id": str(node.id),
        "resolved_range_location_id": str(
            app_session.execute(select(RangeLocation)).scalar_one().id
        ),
    }]
    data = ParsedImportData(
        parser_id="v1_standard",
        range_assignments=[
            ImportRangeAssignmentRow(
                source_row=3, personal_number="12345", full_name="ישראל ישראלי",
                hierarchy_node_name="מדור א", range_type="live", date="2024-06-15",
                range_location_name="מטווח דרומי",
            )
        ],
    )
    result = _resolve_range_assignments(app_session, data, admin, resolved_events)
    row = result[0]
    assert row["action"] == "new"
    assert row["resolved_range_event_id"] is None
    assert row["matched_session_row"] == 2


def test_resolve_range_assignments_soldier_not_found_error(app_session):
    admin = create_soldier(app_session, personal_number="admin-6", role="admin")
    data = ParsedImportData(
        parser_id="v1_standard",
        range_assignments=[
            ImportRangeAssignmentRow(
                source_row=2, personal_number="99999", full_name="לא קיים",
                range_type="live", date="2024-06-15", range_location_name="מטווח דרומי",
            )
        ],
    )
    result = _resolve_range_assignments(app_session, data, admin, [])
    assert result[0]["action"] == "error"
```

Add `from sqlalchemy import select` and `from app.db.models import RangeLocation` at the top of the test file if not already imported for range tests from Task 4.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_import_sessions_resolvers.py -k range_assignments -v`
Expected: FAIL (`_resolve_range_assignments` doesn't exist)

- [ ] **Step 3: Implement `_resolve_range_assignments`**

Add `RangeAssignment, RangeAttendanceStatus` to the `from app.db.models import (...)` block in `import_sessions.py`. Add after `_resolve_range_events` (from Task 4):

```python
def _resolve_range_assignments(
    session: Session,
    data: ParsedImportData,
    actor: Soldier,
    resolved_range_events: list[dict],
    overrides: dict[str, dict] | None = None,
) -> list[dict]:
    overrides = overrides or {}

    soldiers_by_pn = {s.personal_number: s for s in session.execute(select(Soldier)).scalars()}
    soldiers_by_full_name: dict[str, list[Soldier]] = {}
    for s in soldiers_by_pn.values():
        soldiers_by_full_name.setdefault(s.full_name, []).append(s)

    existing_events = session.execute(select(RangeEvent)).scalars().all()
    existing_event_by_key: dict[tuple, RangeEvent] = {}
    for ev in existing_events:
        key = (ev.hierarchy_node_id, ev.range_type, ev.date.isoformat(), ev.range_location_id)
        existing_event_by_key[key] = ev

    session_event_by_key: dict[tuple, dict] = {}
    for ev_row in resolved_range_events:
        if (
            ev_row["action"] != "new"
            or not ev_row.get("resolved_hierarchy_node_id")
            or not ev_row.get("resolved_range_location_id")
        ):
            continue
        key = (
            uuid.UUID(ev_row["resolved_hierarchy_node_id"]), ev_row["range_type"],
            ev_row["date"], uuid.UUID(ev_row["resolved_range_location_id"]),
        )
        session_event_by_key[key] = ev_row

    existing_assignment_pairs = {
        (a.soldier_id, a.range_event_id) for a in session.execute(select(RangeAssignment)).scalars()
    }

    out = []
    for row in data.range_assignments:
        errors: list[str] = []
        warnings: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        personal_number = field("personal_number", row.personal_number)
        full_name = field("full_name", row.full_name)
        hierarchy_node_name = field("hierarchy_node_name", row.hierarchy_node_name)
        range_type = field("range_type", row.range_type)
        event_date = field("date", row.date)
        range_location_name = field("range_location_name", row.range_location_name)
        is_reserve = field("is_reserve", row.is_reserve)
        is_draft = field("is_draft", row.is_draft)
        attendance_status = field("attendance_status", row.attendance_status) or RangeAttendanceStatus.pending.value
        note = field("note", row.note)

        soldier = soldiers_by_pn.get(personal_number) if personal_number else None
        if soldier is not None:
            if soldier.full_name != full_name:
                errors.append(
                    f"שם מלא '{full_name}' אינו תואם לחייל עם מספר אישי '{personal_number}' ('{soldier.full_name}')"
                )
        else:
            candidates = soldiers_by_full_name.get(full_name, []) if full_name else []
            if len(candidates) == 1:
                soldier = candidates[0]
                warnings.append(f"נמצא לפי שם — מספר אישי '{personal_number}' לא נמצא")
            elif len(candidates) > 1:
                errors.append(f"מספר אישי '{personal_number}' לא נמצא ושם '{full_name}' אינו חד משמעי")
            else:
                errors.append(f"לא נמצא חייל עם מספר אישי '{personal_number}' או שם '{full_name}'")

        resolved_node = None
        if hierarchy_node_name:
            resolved_node = session.execute(
                select(HierarchyNode).where(HierarchyNode.name == hierarchy_node_name)
            ).scalar_one_or_none()
            if resolved_node is None:
                errors.append(f"יחידה לא מזוהה '{hierarchy_node_name}'")

        location = session.execute(
            select(RangeLocation).where(RangeLocation.name == range_location_name)
        ).scalar_one_or_none() if range_location_name else None
        if location is None:
            errors.append(f"מיקום מטווח לא מזוהה '{range_location_name}'")

        if range_type not in (rt.value for rt in RangeType):
            errors.append(f"סוג מטווח לא תקין '{range_type}'")

        resolved_range_event_id: str | None = None
        matched_session_row: int | None = None
        if resolved_node is not None and location is not None and event_date and range_type in (rt.value for rt in RangeType):
            key = (resolved_node.id, range_type, event_date, location.id)
            existing_match = existing_event_by_key.get(key)
            session_match = session_event_by_key.get(key)
            if existing_match is not None:
                resolved_range_event_id = str(existing_match.id)
            elif session_match is not None:
                matched_session_row = session_match["row"]
            else:
                errors.append("לא נמצא מטווח תואם (יחידה, סוג, תאריך ומיקום)")

        action = "error" if errors else "new"

        if action == "new" and soldier is not None and actor.role != "admin":
            if soldier.hierarchy_node_id is None or not is_node_in_actor_scope(
                session=session, actor=actor, node_id=soldier.hierarchy_node_id
            ):
                action = "out_of_scope"

        if (
            action == "new"
            and soldier is not None
            and resolved_range_event_id is not None
            and (soldier.id, uuid.UUID(resolved_range_event_id)) in existing_assignment_pairs
        ):
            action = "skip"

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "warnings": warnings,
            "personal_number": personal_number,
            "full_name": full_name,
            "range_type": range_type,
            "date": event_date,
            "range_location_name": range_location_name,
            "is_reserve": is_reserve,
            "is_draft": is_draft,
            "attendance_status": attendance_status,
            "note": note,
            "resolved_soldier_id": str(soldier.id) if soldier is not None else None,
            "resolved_range_event_id": resolved_range_event_id,
            "matched_session_row": matched_session_row,
        })
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_import_sessions_resolvers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/import_sessions.py backend/tests/test_import_sessions_resolvers.py
git commit -m "feat: add range_assignments import resolver"
```

---

### Task 6: Wire the 3 resolvers into `_resolve_and_score`

**Files:**
- Modify: `backend/app/services/import_sessions.py`
- Test: `backend/app/services/tests/test_import_sessions_service.py`

**Interfaces:**
- Consumes: `_resolve_range_locations`, `_resolve_range_events`, `_resolve_range_assignments` (Tasks 4–5).
- Produces: `_resolve_and_score(...)`'s returned dict gains keys `range_locations`, `range_events`, `range_assignments`.

- [ ] **Step 1: Write the failing test**

Read `test_import_sessions_service.py` first to match its `create_session`-based test convention (it typically builds an in-memory `.xlsx` via `openpyxl.Workbook()`, calls `create_session(...)`, and inspects `sess.parsed_state`). Add:

```python
def test_create_session_resolves_range_sheets(app_session):
    admin = create_soldier(app_session, personal_number="admin-7", role="admin")
    node = create_node(app_session, name="מדור א", level="group")
    create_range_location(app_session, name="מטווח דרומי")

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws_loc = wb.create_sheet("range_locations")
    ws_loc.append(["name", "active"])
    ws_loc.append(["מטווח חדש", "true"])
    buf = io.BytesIO()
    wb.save(buf)

    sess = create_session(app_session, filename="ranges.xlsx", content=buf.getvalue(), actor=admin)
    assert len(sess.parsed_state["range_locations"]) == 1
    assert sess.parsed_state["range_locations"][0]["action"] == "new"
    assert sess.parsed_state["range_events"] == []
    assert sess.parsed_state["range_assignments"] == []
```

(Add `import io` and `import openpyxl` at the top of the test file if not already present, matching the existing tests' imports.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/app/services/tests/test_import_sessions_service.py::test_create_session_resolves_range_sheets -v`
Expected: FAIL with `KeyError: 'range_locations'`

- [ ] **Step 3: Wire the resolvers into `_resolve_and_score`**

In `_resolve_and_score` (`import_sessions.py`), add these lines after the `duty_shifts = _resolve_duty_shifts(...)` line and before the `return {`:

```python
    range_events = _resolve_range_events(session, data, actor, node_by_name, node_by_row, fo.get("range_events", {}))
```

Then add these entries to the returned dict (alongside `"duty_shifts": duty_shifts,`):

```python
        "range_locations": _resolve_range_locations(session, data, fo.get("range_locations", {})),
        "range_events": range_events,
        "range_assignments": _resolve_range_assignments(session, data, actor, range_events, fo.get("range_assignments", {})),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/app/services/tests/test_import_sessions_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/import_sessions.py backend/app/services/tests/test_import_sessions_service.py
git commit -m "feat: wire range resolvers into import session creation"
```

---

### Task 7: Apply blocks — `range_locations`, `range_events`, `range_assignments`

**Files:**
- Modify: `backend/app/services/import_sessions.py`
- Test: `backend/app/services/tests/test_import_sessions_service.py`

**Interfaces:**
- Consumes: resolved row dicts from Task 6; `create_range_location` service function (`app/services/range_locations.py`).
- Produces: `confirm_session(...)` creates/updates `RangeLocation`/`RangeEvent`/`RangeAssignment` rows and includes `created_range_locations`, `created_range_events`, `created_range_assignments` id-lists in `import_session.created_links`.

- [ ] **Step 1: Write the failing test**

Add to `backend/app/services/tests/test_import_sessions_service.py`:

```python
from app.db.models import RangeAssignment, RangeEvent, RangeLocation
from app.services.import_sessions import confirm_session


def test_confirm_session_creates_range_event_and_assignment(app_session):
    admin = create_soldier(app_session, personal_number="admin-8", role="admin")
    node = create_node(app_session, name="מדור א", level="group")
    soldier = create_soldier(app_session, personal_number="12345", full_name="ישראל ישראלי", hierarchy_node_id=node.id)
    create_range_location(app_session, name="מטווח דרומי")

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws_ev = wb.create_sheet("range_events")
    ws_ev.append([
        "hierarchy_node_name", "range_type", "date", "range_location_name", "required_count",
    ])
    ws_ev.append(["מדור א", "live", "15.06.2024", "מטווח דרומי", "10"])
    ws_as = wb.create_sheet("range_assignments")
    ws_as.append(["personal_number", "full_name", "hierarchy_node_name", "range_type", "date", "range_location_name"])
    ws_as.append(["12345", "ישראל ישראלי", "מדור א", "live", "15.06.2024", "מטווח דרומי"])
    buf = io.BytesIO()
    wb.save(buf)

    sess = create_session(app_session, filename="ranges.xlsx", content=buf.getvalue(), actor=admin)
    result = confirm_session(app_session, session_id=sess.id, actor=admin)

    assert result["errors"] == []
    events = app_session.execute(select(RangeEvent)).scalars().all()
    assert len(events) == 1
    assert events[0].required_count == 10
    assignments = app_session.execute(select(RangeAssignment)).scalars().all()
    assert len(assignments) == 1
    assert assignments[0].soldier_id == soldier.id
    assert assignments[0].range_event_id == events[0].id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/app/services/tests/test_import_sessions_service.py::test_confirm_session_creates_range_event_and_assignment -v`
Expected: FAIL (no rows created — `confirm_session` doesn't process `range_events`/`range_assignments` yet)

- [ ] **Step 3: Add the 3 apply blocks**

Add `from app.services.range_locations import create_range_location` to the imports at the top of `import_sessions.py`.

In `confirm_session`, add to the declarations near the top (alongside `shift_row_to_id: dict[int, uuid.UUID] = {}`):

```python
    created_range_locations: list[str] = []
    created_range_events: list[str] = []
    created_range_assignments: list[str] = []
    range_event_row_to_id: dict[int, uuid.UUID] = {}
```

Add these 3 blocks right after the `# ── Duty locations ──` block (after line 1293):

```python
    # ── Range locations ─────────────────────────────────────────────────
    for row in state.get("range_locations", []):
        effective = _effective_action(selections, "range_locations", row)
        if row["action"] == "error" or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                if effective == "new":
                    new_loc = create_range_location(session, name=row["name"], actor_id=actor.id)
                    if row.get("active") is not None:
                        new_loc.active = row["active"]
                    created += 1
                    created_range_locations.append(str(new_loc.id))
                elif effective == "update" and row.get("existing_id"):
                    loc = session.get(RangeLocation, uuid.UUID(row["existing_id"]))
                    if loc is not None:
                        loc.name = row["name"]
                        if row.get("active") is not None:
                            loc.active = row["active"]
                        updated += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "range_locations", "error": str(exc)})

    # ── Range events ─────────────────────────────────────────────────────
    for row in state.get("range_events", []):
        effective = _effective_action(selections, "range_events", row)
        if row["action"] in ("error", "out_of_scope") or effective == "skip":
            skipped += 1
            continue
        if effective != "new":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                event = RangeEvent(
                    hierarchy_node_id=uuid.UUID(row["resolved_hierarchy_node_id"]),
                    range_type=row["range_type"],
                    date=date_type.fromisoformat(row["date"]),
                    range_location_id=uuid.UUID(row["resolved_range_location_id"]),
                    required_count=row["required_count"],
                    reserve_count=row.get("reserve_count") or 0,
                    status=row.get("status") or "planned",
                    start_time=row.get("start_time"),
                    end_time=row.get("end_time"),
                    arrival_instructions=row.get("arrival_instructions"),
                    contact_name=row.get("contact_name"),
                    contact_phone=row.get("contact_phone"),
                    notes=row.get("notes"),
                    created_by=actor.id,
                )
                session.add(event)
                session.flush()
            created += 1
            created_range_events.append(str(event.id))
            range_event_row_to_id[row["row"]] = event.id
        except Exception as exc:
            errors.append({"row": row["row"], "type": "range_events", "error": str(exc)})

    # ── Range assignments ───────────────────────────────────────────────
    for row in state.get("range_assignments", []):
        effective = _effective_action(selections, "range_assignments", row)
        if row["action"] in ("error", "out_of_scope", "skip") or effective == "skip":
            skipped += 1
            continue
        if effective != "new":
            skipped += 1
            continue
        try:
            if row.get("resolved_range_event_id"):
                range_event_id = uuid.UUID(row["resolved_range_event_id"])
            elif row.get("matched_session_row") is not None:
                mapped = range_event_row_to_id.get(row["matched_session_row"])
                if mapped is None:
                    errors.append({
                        "row": row["row"], "type": "range_assignments",
                        "error": "המטווח המתאים לא נוצר (דולג או נכשל)",
                    })
                    continue
                range_event_id = mapped
            else:
                errors.append({"row": row["row"], "type": "range_assignments", "error": "לא נמצא מטווח תואם"})
                continue

            with session.begin_nested():
                assignment = RangeAssignment(
                    range_event_id=range_event_id,
                    soldier_id=uuid.UUID(row["resolved_soldier_id"]),
                    is_reserve=row.get("is_reserve") or False,
                    is_draft=row.get("is_draft") or False,
                    attendance_status=row.get("attendance_status") or "pending",
                    note=row.get("note"),
                )
                session.add(assignment)
            created += 1
            created_range_assignments.append(str(assignment.id))
        except Exception as exc:
            errors.append({"row": row["row"], "type": "range_assignments", "error": str(exc)})
```

Finally, extend `import_session.created_links = {...}` (near the end of `confirm_session`, line ~1924) with:

```python
        "range_locations": created_range_locations,
        "range_events": created_range_events,
        "range_assignments": created_range_assignments,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/app/services/tests/test_import_sessions_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/import_sessions.py backend/app/services/tests/test_import_sessions_service.py
git commit -m "feat: apply range_locations/range_events/range_assignments on import confirm"
```

---

### Task 8: Resolvers + apply — `soldier_range_qualifications`, `range_excusal_requests`

**Files:**
- Modify: `backend/app/services/import_approvals.py`
- Modify: `backend/app/services/import_sessions.py` (wire resolvers into `_resolve_and_score`; add 2 apply blocks to `confirm_session`)
- Test: `backend/app/services/tests/test_import_approvals_service.py`

**Interfaces:**
- Consumes: `ImportSoldierRangeQualificationRow`, `ImportRangeExcusalRequestRow` (Task 1).
- Produces: `resolve_soldier_range_qualifications(session, data, overrides=None) -> list[dict]` (keys: `row, action, errors, id, soldier_personal_number, resolved_soldier_id, range_type, valid_until, existing_id`); `resolve_range_excusal_requests(session, data, overrides=None) -> list[dict]` (keys: `row, action, errors, id, soldier_personal_number, resolved_soldier_id, requested_by_personal_number, resolved_requested_by_id, hierarchy_node_name, range_type, date, range_location_name, resolved_range_event_id, resolved_range_assignment_id, reason, status, decided_by_personal_number, resolved_decided_by_id, decision_note, existing_id`).

- [ ] **Step 1: Write the failing tests**

Read the top of `test_import_approvals_service.py` first to match its fixtures/imports. Add:

```python
from app.db.models import RangeAssignment, RangeExcusalRequest, RangeType, SoldierRangeQualification
from app.services.import_approvals import resolve_range_excusal_requests, resolve_soldier_range_qualifications
from app.services.import_parsers.schema import ImportRangeExcusalRequestRow, ImportSoldierRangeQualificationRow
from tests.helpers import create_node, create_range_assignment, create_range_event, create_range_location, create_soldier


def test_resolve_soldier_range_qualifications_new_and_update(app_session):
    soldier = create_soldier(app_session, personal_number="12345", full_name="ישראל ישראלי")
    existing = SoldierRangeQualification(soldier_id=soldier.id, range_type="live", valid_until=date(2024, 1, 1))
    app_session.add(existing)
    app_session.flush()

    data = ParsedImportData(
        parser_id="v1_standard",
        soldier_range_qualifications=[
            ImportSoldierRangeQualificationRow(source_row=2, id=str(existing.id), soldier_personal_number="12345", range_type="live", valid_until="2025-01-01"),
            ImportSoldierRangeQualificationRow(source_row=3, soldier_personal_number="12345", range_type="alal", valid_until="2025-06-01"),
        ],
    )
    result = resolve_soldier_range_qualifications(app_session, data)
    assert result[0]["action"] == "update"
    assert result[0]["existing_id"] == str(existing.id)
    assert result[1]["action"] == "new"


def test_resolve_soldier_range_qualifications_invalid_range_type_error(app_session):
    create_soldier(app_session, personal_number="12345", full_name="ישראל ישראלי")
    data = ParsedImportData(
        parser_id="v1_standard",
        soldier_range_qualifications=[
            ImportSoldierRangeQualificationRow(source_row=2, soldier_personal_number="12345", range_type="bogus", valid_until="2025-01-01"),
        ],
    )
    result = resolve_soldier_range_qualifications(app_session, data)
    assert result[0]["action"] == "error"


def test_resolve_range_excusal_requests_matches_existing_assignment(app_session):
    node = create_node(app_session, name="מדור א", level="group")
    loc = create_range_location(app_session, name="מטווח דרומי")
    soldier = create_soldier(app_session, personal_number="12345", full_name="ישראל ישראלי", hierarchy_node_id=node.id)
    event = create_range_event(app_session, hierarchy_node=node, range_location=loc)
    assignment = create_range_assignment(app_session, range_event=event, soldier=soldier)

    data = ParsedImportData(
        parser_id="v1_standard",
        range_excusal_requests=[
            ImportRangeExcusalRequestRow(
                source_row=2, soldier_personal_number="12345", requested_by_personal_number="12345",
                hierarchy_node_name="מדור א", range_type="live", date="2024-06-15",
                range_location_name="מטווח דרומי", reason="חופשה", status="pending",
            )
        ],
    )
    result = resolve_range_excusal_requests(app_session, data)
    row = result[0]
    assert row["action"] == "new"
    assert row["resolved_range_event_id"] == str(event.id)
    assert row["resolved_range_assignment_id"] == str(assignment.id)


def test_resolve_range_excusal_requests_invalid_status_error(app_session):
    create_soldier(app_session, personal_number="12345", full_name="ישראל ישראלי")
    data = ParsedImportData(
        parser_id="v1_standard",
        range_excusal_requests=[
            ImportRangeExcusalRequestRow(
                source_row=2, soldier_personal_number="12345", range_type="live",
                date="2024-06-15", range_location_name="מטווח דרומי", status="not_a_status",
            )
        ],
    )
    result = resolve_range_excusal_requests(app_session, data)
    assert result[0]["action"] == "error"
```

(Add `from datetime import date` at the top of the test file if not already present.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/app/services/tests/test_import_approvals_service.py -k range -v`
Expected: FAIL (functions don't exist yet)

- [ ] **Step 3: Implement both resolvers in `import_approvals.py`**

Add to the `from app.db.models import (...)` block: `HierarchyNode, RangeAssignment, RangeEvent, RangeExcusalStatus, RangeLocation, RangeType, SoldierRangeQualification`. Add after `resolve_soldier_exemptions` (before `resolve_exemption_requests`):

```python
def resolve_soldier_range_qualifications(session: Session, data: ParsedImportData, overrides: dict[str, dict] | None = None) -> list[dict]:
    overrides = overrides or {}
    soldiers_by_pn = _soldiers_by_pn(session)
    out = []
    for row in data.soldier_range_qualifications:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        soldier_pn = field("soldier_personal_number", row.soldier_personal_number)
        range_type = field("range_type", row.range_type)
        valid_until = field("valid_until", row.valid_until)

        soldier = soldiers_by_pn.get(soldier_pn) if soldier_pn else None
        if soldier is None:
            errors.append(f"חייל לא מזוהה '{soldier_pn}'")
        if range_type not in (rt.value for rt in RangeType):
            errors.append(f"סוג מטווח לא תקין '{range_type}'")
        if not valid_until:
            errors.append("חסר תאריך תוקף")

        existing = None
        if row.id:
            try:
                existing = session.get(SoldierRangeQualification, uuid.UUID(row.id))
            except ValueError:
                errors.append(f"מזהה לא תקין '{row.id}'")

        action = "error" if errors else ("update" if existing is not None else "new")
        out.append({
            "row": row.source_row, "action": action, "errors": errors,
            "id": row.id, "soldier_personal_number": soldier_pn,
            "resolved_soldier_id": str(soldier.id) if soldier else None,
            "range_type": range_type, "valid_until": valid_until,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def resolve_range_excusal_requests(session: Session, data: ParsedImportData, overrides: dict[str, dict] | None = None) -> list[dict]:
    overrides = overrides or {}
    soldiers_by_pn = _soldiers_by_pn(session)
    nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}
    locations_by_name = {loc.name: loc for loc in session.execute(select(RangeLocation)).scalars()}
    events = session.execute(select(RangeEvent)).scalars().all()
    events_by_key = {
        (ev.hierarchy_node_id, ev.range_type, ev.date.isoformat(), ev.range_location_id): ev
        for ev in events
    }
    assignments_by_event_and_soldier = {
        (a.range_event_id, a.soldier_id): a for a in session.execute(select(RangeAssignment)).scalars()
    }

    out = []
    for row in data.range_excusal_requests:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        soldier_pn = field("soldier_personal_number", row.soldier_personal_number)
        requested_by_pn = field("requested_by_personal_number", row.requested_by_personal_number)
        hierarchy_node_name = field("hierarchy_node_name", row.hierarchy_node_name)
        range_type = field("range_type", row.range_type)
        event_date = field("date", row.date)
        range_location_name = field("range_location_name", row.range_location_name)
        reason = field("reason", row.reason)
        status = field("status", row.status)
        decided_by_pn = field("decided_by_personal_number", row.decided_by_personal_number)
        decision_note = field("decision_note", row.decision_note)

        soldier = soldiers_by_pn.get(soldier_pn) if soldier_pn else None
        if soldier is None:
            errors.append(f"חייל לא מזוהה '{soldier_pn}'")
        requested_by = soldiers_by_pn.get(requested_by_pn) if requested_by_pn else None
        if requested_by_pn and requested_by is None:
            errors.append(f"מבקש לא מזוהה '{requested_by_pn}'")
        decided_by = soldiers_by_pn.get(decided_by_pn) if decided_by_pn else None
        if decided_by_pn and decided_by is None:
            errors.append(f"מחליט לא מזוהה '{decided_by_pn}'")
        if status not in (s.value for s in RangeExcusalStatus):
            errors.append(f"סטטוס לא תקין '{status}'")

        node = nodes_by_name.get(hierarchy_node_name) if hierarchy_node_name else None
        location = locations_by_name.get(range_location_name) if range_location_name else None
        event = None
        assignment = None
        if node is not None and location is not None and event_date and range_type in (rt.value for rt in RangeType):
            event = events_by_key.get((node.id, range_type, event_date, location.id))
        if event is not None and soldier is not None:
            assignment = assignments_by_event_and_soldier.get((event.id, soldier.id))

        existing = None
        if row.id:
            try:
                existing = session.get(RangeExcusalRequest, uuid.UUID(row.id))
            except ValueError:
                errors.append(f"מזהה לא תקין '{row.id}'")

        action = "error" if errors else ("update" if existing is not None else "new")
        out.append({
            "row": row.source_row, "action": action, "errors": errors,
            "id": row.id, "soldier_personal_number": soldier_pn,
            "resolved_soldier_id": str(soldier.id) if soldier else None,
            "requested_by_personal_number": requested_by_pn,
            "resolved_requested_by_id": str(requested_by.id) if requested_by else None,
            "hierarchy_node_name": hierarchy_node_name, "range_type": range_type, "date": event_date,
            "range_location_name": range_location_name,
            "resolved_range_event_id": str(event.id) if event else None,
            "resolved_range_assignment_id": str(assignment.id) if assignment else None,
            "reason": reason, "status": status,
            "decided_by_personal_number": decided_by_pn,
            "resolved_decided_by_id": str(decided_by.id) if decided_by else None,
            "decision_note": decision_note,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/app/services/tests/test_import_approvals_service.py -v`
Expected: PASS

- [ ] **Step 5: Wire into `_resolve_and_score` and add apply blocks (backed by an integration-style test)**

Add to the `from app.services.import_approvals import (...)` block in `import_sessions.py`: `resolve_range_excusal_requests, resolve_soldier_range_qualifications`.

Add to the returned dict in `_resolve_and_score` (alongside `"soldier_exemptions": ...`):

```python
        "soldier_range_qualifications": resolve_soldier_range_qualifications(session, data, fo.get("soldier_range_qualifications", {})),
        "range_excusal_requests": resolve_range_excusal_requests(session, data, fo.get("range_excusal_requests", {})),
```

Add `RangeExcusalRequest, SoldierRangeQualification` to the `from app.db.models import (...)` block in `import_sessions.py` (if not already added by an earlier task).

Add these 2 apply blocks in `confirm_session`, right after the `# ── Soldier exemptions ──` block (after line 1779):

```python
    # ── Soldier range qualifications ──────────────────────────────────────
    for row in state.get("soldier_range_qualifications", []):
        effective = _effective_action(selections, "soldier_range_qualifications", row)
        if row["action"] == "error" or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                if effective == "new":
                    srq = SoldierRangeQualification(
                        soldier_id=uuid.UUID(row["resolved_soldier_id"]),
                        range_type=row["range_type"],
                        valid_until=date_type.fromisoformat(row["valid_until"]),
                    )
                    session.add(srq)
                    created += 1
                elif effective == "update" and row.get("existing_id"):
                    srq = session.get(SoldierRangeQualification, uuid.UUID(row["existing_id"]))
                    if srq is not None:
                        srq.range_type = row["range_type"]
                        srq.valid_until = date_type.fromisoformat(row["valid_until"])
                        updated += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "soldier_range_qualifications", "error": str(exc)})

    # ── Range excusal requests ──────────────────────────────────────────
    for row in state.get("range_excusal_requests", []):
        effective = _effective_action(selections, "range_excusal_requests", row)
        if row["action"] == "error" or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                if effective == "new":
                    rer = RangeExcusalRequest(
                        range_assignment_id=(
                            uuid.UUID(row["resolved_range_assignment_id"]) if row.get("resolved_range_assignment_id") else None
                        ),
                        range_event_id=(
                            uuid.UUID(row["resolved_range_event_id"]) if row.get("resolved_range_event_id") else None
                        ),
                        requested_by=(
                            uuid.UUID(row["resolved_requested_by_id"]) if row.get("resolved_requested_by_id") else None
                        ),
                        reason=row.get("reason") or "",
                        status=row["status"],
                    )
                    if row.get("resolved_decided_by_id"):
                        rer.decided_by = uuid.UUID(row["resolved_decided_by_id"])
                        rer.decided_at = datetime.now(UTC)
                    rer.decision_note = row.get("decision_note")
                    session.add(rer)
                    created += 1
                elif effective == "update" and row.get("existing_id"):
                    rer = session.get(RangeExcusalRequest, uuid.UUID(row["existing_id"]))
                    if rer is not None:
                        rer.status = row["status"]
                        if row.get("reason") is not None:
                            rer.reason = row["reason"]
                        if row.get("resolved_decided_by_id"):
                            rer.decided_by = uuid.UUID(row["resolved_decided_by_id"])
                        rer.decision_note = row.get("decision_note")
                        updated += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "range_excusal_requests", "error": str(exc)})
```

Now add the corresponding integration-style test to `backend/app/services/tests/test_import_sessions_service.py`:

```python
def test_confirm_session_creates_range_qualification_and_excusal(app_session):
    admin = create_soldier(app_session, personal_number="admin-9", role="admin")
    node = create_node(app_session, name="מדור א", level="group")
    soldier = create_soldier(app_session, personal_number="12345", full_name="ישראל ישראלי", hierarchy_node_id=node.id)
    loc = create_range_location(app_session, name="מטווח דרומי")
    event = create_range_event(app_session, hierarchy_node=node, range_location=loc)
    create_range_assignment(app_session, range_event=event, soldier=soldier)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws_q = wb.create_sheet("soldier_range_qualifications")
    ws_q.append(["soldier_personal_number", "range_type", "valid_until"])
    ws_q.append(["12345", "live", "01.01.2025"])
    ws_ex = wb.create_sheet("range_excusal_requests")
    ws_ex.append(["soldier_personal_number", "hierarchy_node_name", "range_type", "date", "range_location_name", "reason", "status"])
    ws_ex.append(["12345", "מדור א", "live", "15.06.2024", "מטווח דרומי", "חופשה", "pending"])
    buf = io.BytesIO()
    wb.save(buf)

    sess = create_session(app_session, filename="ranges.xlsx", content=buf.getvalue(), actor=admin)
    result = confirm_session(app_session, session_id=sess.id, actor=admin)

    assert result["errors"] == []
    quals = app_session.execute(select(SoldierRangeQualification)).scalars().all()
    assert len(quals) == 1
    assert quals[0].valid_until.isoformat() == "2025-01-01"
    excusals = app_session.execute(select(RangeExcusalRequest)).scalars().all()
    assert len(excusals) == 1
    assert excusals[0].range_assignment_id is not None
```

- [ ] **Step 6: Run all import-session tests**

Run: `pytest backend/app/services/tests/test_import_approvals_service.py backend/app/services/tests/test_import_sessions_service.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/import_approvals.py backend/app/services/import_sessions.py backend/app/services/tests/test_import_approvals_service.py backend/app/services/tests/test_import_sessions_service.py
git commit -m "feat: add soldier_range_qualifications and range_excusal_requests import support"
```

---

### Task 9: Row summary counts in `routes/import_sessions.py`

**Files:**
- Modify: `backend/app/routes/import_sessions.py`
- Test: `backend/tests/integration/test_import_sessions_config_confirm.py`

**Interfaces:**
- Consumes: `parsed_state` keys added in Tasks 6 & 8.
- Produces: `GET /import/sessions` and `GET /import/sessions/{id}`'s summary payload includes `row_summary.range_locations`, `.range_events`, `.range_assignments`, `.soldier_range_qualifications`, `.range_excusal_requests`.

- [ ] **Step 1: Write the failing test**

Read `test_import_sessions_config_confirm.py` first to match its HTTP-client/fixture convention (it typically posts an `.xlsx` to `/import/sessions` via a `client` fixture and inspects the JSON response). Add:

```python
def test_session_row_summary_includes_range_sheets(client, admin_headers):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("range_locations")
    ws.append(["name", "active"])
    ws.append(["מטווח חדש", "true"])
    buf = io.BytesIO()
    wb.save(buf)

    resp = client.post(
        "/import/sessions",
        files={"file": ("ranges.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    get_resp = client.get(f"/import/sessions/{session_id}", headers=admin_headers)
    assert get_resp.status_code == 200
```

(Match the exact fixture names — `client`/`admin_headers` or equivalent — used by the other tests already in this file; adjust the two calls above to that convention before running.)

Then add the row_summary assertion via the sessions-list endpoint, matching how the file's existing tests check `row_summary`:

```python
    list_resp = client.get("/import/sessions", headers=admin_headers)
    summary = next(s for s in list_resp.json() if s["id"] == session_id)
    assert summary["row_summary"]["range_locations"] == 1
    assert summary["row_summary"]["range_events"] == 0
    assert summary["row_summary"]["range_assignments"] == 0
    assert summary["row_summary"]["soldier_range_qualifications"] == 0
    assert summary["row_summary"]["range_excusal_requests"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/integration/test_import_sessions_config_confirm.py::test_session_row_summary_includes_range_sheets -v`
Expected: FAIL with `KeyError: 'range_locations'`

- [ ] **Step 3: Add the 5 counts**

In `_session_summary` (`routes/import_sessions.py`), add to the `row_summary` dict:

```python
            "range_locations": len(state.get("range_locations", [])),
            "range_events": len(state.get("range_events", [])),
            "range_assignments": len(state.get("range_assignments", [])),
            "soldier_range_qualifications": len(state.get("soldier_range_qualifications", [])),
            "range_excusal_requests": len(state.get("range_excusal_requests", [])),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/integration/test_import_sessions_config_confirm.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/import_sessions.py backend/tests/integration/test_import_sessions_config_confirm.py
git commit -m "feat: include range sheets in import session row summary"
```

---

### Task 10: Export wiring — `config_export.py`, `import_excel.py`, `approvals_export.py`

**Files:**
- Modify: `backend/app/routes/config_export.py`
- Modify: `backend/app/routes/import_excel.py`
- Modify: `backend/app/routes/approvals_export.py`
- Test: `backend/tests/integration/test_approvals_export_import_e2e.py` (extend with range coverage), plus new focused tests where noted below.

**Interfaces:**
- Produces: `GET /config/export?sheets=range_locations` returns a workbook with a `range_locations` sheet matching the `range_locations` import layout; `GET /import/export?sheets=range_events,range_assignments` returns a workbook with those sheets matching their import layouts; `GET /approvals/export` includes `soldier_range_qualifications`/`range_excusal_requests` sheets; `GET /import/template` includes example rows for all 5 new sheets.

- [ ] **Step 1: Write the failing tests**

Find the existing test file(s) that exercise `/config/export`, `/import/export`, and `/import/template` (search for `config/export` and `import/export` under `backend/tests/integration/`) and add one focused test per router to whichever file already covers that router, following its existing request/assertion style (upload a request to the endpoint, load the returned bytes with `openpyxl.load_workbook`, assert on sheet names and cell values). At minimum:

```python
def test_config_export_includes_range_locations(client, admin_headers):
    # ... create a RangeLocation via the test DB session fixture ...
    resp = client.get("/config/export?sheets=range_locations", headers=admin_headers)
    assert resp.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert "range_locations" in wb.sheetnames
    rows = list(wb["range_locations"].iter_rows(values_only=True))
    assert rows[0] == ("name", "active")


def test_import_export_includes_range_events_and_assignments(client, admin_headers):
    # ... create a RangeEvent + RangeAssignment via the test DB session fixture ...
    resp = client.get("/import/export?sheets=range_events,range_assignments", headers=admin_headers)
    assert resp.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert "range_events" in wb.sheetnames
    assert "range_assignments" in wb.sheetnames


def test_approvals_export_includes_range_sheets(client, admin_headers):
    resp = client.get("/approvals/export", headers=admin_headers)
    assert resp.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert "soldier_range_qualifications" in wb.sheetnames
    assert "range_excusal_requests" in wb.sheetnames


def test_import_template_includes_range_sheets(client, admin_headers):
    resp = client.get("/import/template", headers=admin_headers)
    assert resp.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    for name in ("range_locations", "range_events", "range_assignments", "soldier_range_qualifications", "range_excusal_requests"):
        assert name in wb.sheetnames
```

Adjust fixture names (`client`, `admin_headers`, however the DB session is exposed) to match whatever convention the file you're extending already uses — read that file's existing tests first.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/integration -k "range_locations or range_events_and_assignments or range_sheets" -v`
Expected: FAIL (sheets not present / 400s if the sheet key isn't recognized)

- [ ] **Step 3a: `config_export.py` — add `range_locations`**

Add `RangeLocation` to the `from app.db.models import (...)` block. Add `"range_locations"` to `ALL_SHEETS`. Add:

```python
def _write_range_locations(wb: openpyxl.Workbook, session: Session) -> None:
    ws = wb.create_sheet("range_locations")
    ws.append(["name", "active"])
    for loc in session.execute(select(RangeLocation)).scalars():
        ws.append([loc.name, loc.active])
```

Add `"range_locations": _write_range_locations,` to `_WRITERS`.

- [ ] **Step 3b: `import_excel.py` — add `range_events`/`range_assignments` to the round-trip export, and all 5 sheets to the template**

Add `HierarchyNode` (if not already imported — it is), `RangeAssignment, RangeEvent, RangeLocation` to the `from app.db.models import (...)` block. Add `"range_events", "range_assignments"` to `EXPORT_DATA_SHEETS`.

In `export_current_data`, add lookups (alongside the existing `nodes_by_id`/`duty_types_by_id`/`locations_by_id` block):

```python
    range_locations_by_id = {loc.id: loc for loc in session.execute(select(RangeLocation)).scalars()}
```

Then, after the `assignments` block (before `if "shift_templates" in requested:`), add:

```python
    if "range_events" in requested or "range_assignments" in requested:
        range_events = session.execute(select(RangeEvent)).scalars().all()
    else:
        range_events = []

    if "range_events" in requested:
        ws_re = wb.create_sheet("range_events")
        ws_re.append([
            "hierarchy_node_name", "range_type", "date", "range_location_name",
            "required_count", "reserve_count", "start_time", "end_time",
            "arrival_instructions", "contact_name", "contact_phone", "notes", "status",
        ])
        for ev in range_events:
            node = nodes_by_id.get(ev.hierarchy_node_id)
            loc = range_locations_by_id.get(ev.range_location_id)
            ws_re.append([
                node.name if node else "", ev.range_type, ev.date.strftime("%d.%m.%Y"),
                loc.name if loc else "", ev.required_count, ev.reserve_count,
                ev.start_time or "", ev.end_time or "", ev.arrival_instructions or "",
                ev.contact_name or "", ev.contact_phone or "", ev.notes or "", ev.status,
            ])

    if "range_assignments" in requested:
        range_events_by_id = {ev.id: ev for ev in range_events}
        soldiers_by_id = {s.id: s for s in session.execute(select(Soldier)).scalars()}
        ws_ra = wb.create_sheet("range_assignments")
        ws_ra.append([
            "personal_number", "full_name", "hierarchy_node_name", "range_type", "date",
            "range_location_name", "is_reserve", "is_draft", "attendance_status", "note",
        ])
        for a in session.execute(select(RangeAssignment)).scalars():
            ev = range_events_by_id.get(a.range_event_id)
            if ev is None:
                continue
            soldier = soldiers_by_id.get(a.soldier_id)
            node = nodes_by_id.get(ev.hierarchy_node_id)
            loc = range_locations_by_id.get(ev.range_location_id)
            ws_ra.append([
                soldier.personal_number if soldier else "", soldier.full_name if soldier else "",
                node.name if node else "", ev.range_type, ev.date.strftime("%d.%m.%Y"),
                loc.name if loc else "", "true" if a.is_reserve else "false",
                "true" if a.is_draft else "false", a.attendance_status, a.note or "",
            ])
```

In `download_template`, add example sheets right before the `buf = io.BytesIO()` line at the end:

```python
    ws_rl = wb.create_sheet("range_locations")
    ws_rl.append(["name", "active"])
    ws_rl.append(["מטווח דרומי", "true"])

    ws_re = wb.create_sheet("range_events")
    ws_re.append([
        "hierarchy_node_name", "range_type", "date", "range_location_name",
        "required_count", "reserve_count", "start_time", "end_time",
        "arrival_instructions", "contact_name", "contact_phone", "notes", "status",
    ])
    ws_re.append([
        "מדור א", "live", "20.06.2024", "מטווח דרומי", "10", "2",
        "08:00", "12:00", "התייצבות בשער הראשי", "דני", "050-1234567", "", "planned",
    ])

    ws_ra = wb.create_sheet("range_assignments")
    ws_ra.append([
        "personal_number", "full_name", "hierarchy_node_name", "range_type", "date",
        "range_location_name", "is_reserve", "is_draft", "attendance_status", "note",
    ])
    ws_ra.append(["12345", "ישראל ישראלי", "מדור א", "live", "20.06.2024", "מטווח דרומי", "false", "false", "pending", ""])

    ws_srq = wb.create_sheet("soldier_range_qualifications")
    ws_srq.append(["soldier_personal_number", "range_type", "valid_until"])
    ws_srq.append(["12345", "live", "20.06.2025"])

    ws_rer = wb.create_sheet("range_excusal_requests")
    ws_rer.append([
        "soldier_personal_number", "requested_by_personal_number", "hierarchy_node_name",
        "range_type", "date", "range_location_name", "reason", "status",
    ])
    ws_rer.append(["12345", "12345", "מדור א", "live", "20.06.2024", "מטווח דרומי", "חופשה", "pending"])
```

- [ ] **Step 3c: `approvals_export.py` — add `soldier_range_qualifications`/`range_excusal_requests`**

Add `RangeExcusalRequest, RangeEvent, RangeLocation, SoldierRangeQualification` to the `from app.db.models import (...)` block. Add both names to `ALL_SHEETS`. Add:

```python
def _write_soldier_range_qualifications(wb: openpyxl.Workbook, session: Session, actor: Soldier) -> None:
    ws = wb.create_sheet("soldier_range_qualifications")
    ws.append(["id", "soldier_personal_number", "soldier_name", "range_type", "valid_until"])
    soldiers_by_id = {s.id: s for s in session.execute(select(Soldier)).scalars()}
    for q in session.execute(select(SoldierRangeQualification)).scalars():
        pn, name = _soldier_label(soldiers_by_id, q.soldier_id)
        ws.append([str(q.id), pn, name, q.range_type, q.valid_until.isoformat()])


def _write_range_excusal_requests(wb: openpyxl.Workbook, session: Session, actor: Soldier) -> None:
    ws = wb.create_sheet("range_excusal_requests")
    ws.append([
        "id", "soldier_personal_number", "soldier_name", "requested_by_personal_number",
        "hierarchy_node_name", "range_type", "date", "range_location_name",
        "reason", "status", "decided_by_personal_number", "decision_note", "requested_at",
    ])
    soldiers_by_id = {s.id: s for s in session.execute(select(Soldier)).scalars()}
    nodes_by_id = {n.id: n for n in session.execute(select(HierarchyNode)).scalars()}
    locations_by_id = {loc.id: loc for loc in session.execute(select(RangeLocation)).scalars()}
    events_by_id = {ev.id: ev for ev in session.execute(select(RangeEvent)).scalars()}
    assignments_by_id = {a.id: a for a in session.execute(select(RangeAssignment)).scalars()}
    for r in session.execute(select(RangeExcusalRequest)).scalars():
        assignment = assignments_by_id.get(r.range_assignment_id) if r.range_assignment_id else None
        soldier_id = assignment.soldier_id if assignment else None
        pn, _name = _soldier_label(soldiers_by_id, soldier_id) if soldier_id else ("", "")
        requested_pn = _soldier_label(soldiers_by_id, r.requested_by)[0] if r.requested_by else ""
        decided_pn = _soldier_label(soldiers_by_id, r.decided_by)[0] if r.decided_by else ""
        event = events_by_id.get(r.range_event_id) if r.range_event_id else None
        node = nodes_by_id.get(event.hierarchy_node_id) if event else None
        loc = locations_by_id.get(event.range_location_id) if event else None
        ws.append([
            str(r.id), pn, "", requested_pn,
            node.name if node else "", event.range_type if event else "",
            event.date.isoformat() if event else "", loc.name if loc else "",
            r.reason, r.status, decided_pn, r.decision_note, r.requested_at.isoformat(),
        ])
```

Note `RangeAssignment` also needs adding to the model import block (used above for `assignments_by_id`).

Add both writers to `_WRITERS`:

```python
    "soldier_range_qualifications": _write_soldier_range_qualifications,
    "range_excusal_requests": _write_range_excusal_requests,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/integration -k "range_locations or range_events_and_assignments or range_sheets" -v`
Expected: PASS

- [ ] **Step 5: Run the full backend fast suite**

Run: `pytest -q` (from `backend/`, with the venv active)
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/config_export.py backend/app/routes/import_excel.py backend/app/routes/approvals_export.py backend/tests/integration
git commit -m "feat: export range sheets via config/import/approvals export routers"
```

---

## Self-Review Notes

- **Spec coverage:** all 5 sheets from the design doc are covered — schema (Task 1), parser (Task 2), resolvers (Tasks 4–6, 8), apply blocks (Tasks 7–8), row summary (Task 9), and all three export routers plus the template (Task 10).
- **Corrected design assumptions** (found while reading the real code, applied throughout this plan rather than in the earlier design doc): export routing is 3-way (config/import/approvals), not a single `EXPORT_DATA_SHEETS` list; `SoldierRangeQualification` has no `revoked` column; import apply blocks never call live side-effect service functions.
- **Type consistency:** row dict keys are used identically across each resolver → apply-block pair (e.g. `resolved_range_event_id`/`matched_session_row` from Task 5's `_resolve_range_assignments` are consumed with those exact names in Task 7's apply block).
- **Out of scope for this plan:** the frontend (`ImportSessionReviewPage.tsx` review tabs, `ExportPage.tsx` checkboxes, `RangesPage.tsx` entry-point links) — covered by a separate frontend plan, since the backend alone is independently testable via the API and pytest suite.
