# Config Export/Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Excel export/import for duty types, duty locations, hierarchy (incl. commanders/duty managers), and exemption types — extending the existing session-based import pipeline and adding a new config export endpoint + unified export UI.

**Architecture:** Four new optional sheets (`duty_locations`, `hierarchy`, `duty_types`, `exemption_types`) are added to the `v1_standard` parser and `import_sessions.py` resolve/confirm pipeline, following the exact same parser→resolve→review-tab→confirm shape already used for `soldiers`/`duty_shifts`. A new `GET /config/export` endpoint builds the same 4 sheets from current DB state via openpyxl. The frontend `ExportPage` gains a unified checkbox panel merging this new export with the two existing client-built report exports into one downloaded workbook.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, openpyxl (backend); React, TypeScript, the `xlsx` (SheetJS) package (frontend).

## Global Constraints

- Match by `name` for duty types/locations/exemption types/hierarchy nodes. Soldier references (commander, duty managers) match by **personal number first, falling back to full name if no personal-number match**.
- Import only creates/updates — never deletes rows absent from a sheet.
- No sheet is required — a workbook may contain any subset of the 6 total sheets (existing `soldiers`/`duty_shifts` + these 4 new ones).
- Reuse existing service-layer functions for all writes (`create_node`, `set_commander`, `move_node`, `change_node_level` in `hierarchy.py`; `create_duty_type`/`update_duty_type` , `create_location`/`update_location`, `create_exemption_type`/`update_exemption_type`, `set_exemption_duty_types` in `duty_config.py`; `assign_dm_scope`/`remove_dm_scope` in `dm_scope.py`) rather than writing raw SQLAlchemy mutations in the import service.
- Full spec: `docs/superpowers/specs/2026-07-06-config-export-import-design.md`.

---

## Task 1: Schema — new row models

**Files:**
- Modify: `backend/app/services/import_parsers/schema.py`
- Test: `backend/tests/test_import_parsers_schema.py` (new)

**Interfaces:**
- Produces: `ImportDutyLocationRow`, `ImportHierarchyNodeRow`, `ImportDutyTypeRow`, `ImportExemptionTypeRow` (all `pydantic.BaseModel`), and `ParsedImportData.duty_locations: list[ImportDutyLocationRow]`, `.hierarchy: list[ImportHierarchyNodeRow]`, `.duty_types: list[ImportDutyTypeRow]`, `.exemption_types: list[ImportExemptionTypeRow]` (each defaulting to `[]`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_import_parsers_schema.py
from __future__ import annotations

from app.services.import_parsers.schema import ParsedImportData


def test_parsed_import_data_defaults_new_sheets_to_empty_lists():
    data = ParsedImportData(parser_id="v1_standard")
    assert data.duty_locations == []
    assert data.hierarchy == []
    assert data.duty_types == []
    assert data.exemption_types == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_import_parsers_schema.py -v`
Expected: FAIL — `ParsedImportData` has no field `duty_locations` (pydantic raises on unknown attribute access or the field simply doesn't exist, causing an `AttributeError`).

- [ ] **Step 3: Add the new row models and fields**

In `backend/app/services/import_parsers/schema.py`, after `ImportDutyShiftRow` and before `ParsedImportData`:

```python
class ImportDutyLocationRow(BaseModel):
    source_row: int
    name: str
    base: str | None = None
    active: bool | None = None


class ImportHierarchyNodeRow(BaseModel):
    source_row: int
    name: str
    level: str
    parent_name: str | None = None
    commander_personal_number: str | None = None
    commander_name: str | None = None
    duty_manager_refs: list[str] = []


class ImportDutyTypeRow(BaseModel):
    source_row: int
    name: str
    score_per_day: str
    description: str | None = None
    active: bool | None = None
    reserve_ratio: str | None = None
    reserve_minimum: int | None = None
    is_external: bool | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    instructions: str | None = None
    eligible_unit_names: list[str] = []
    requirements_json: str | None = None


class ImportExemptionTypeRow(BaseModel):
    source_row: int
    name: str
    description: str | None = None
    is_global: bool | None = None
    is_medical: bool | None = None
    is_commander_exemption: bool | None = None
    applies_to_duty_type_names: list[str] = []
```

Then update `ParsedImportData`:

```python
class ParsedImportData(BaseModel):
    soldiers: list[ImportSoldierRow] = []
    duty_shifts: list[ImportDutyShiftRow] = []
    duty_locations: list[ImportDutyLocationRow] = []
    hierarchy: list[ImportHierarchyNodeRow] = []
    duty_types: list[ImportDutyTypeRow] = []
    exemption_types: list[ImportExemptionTypeRow] = []
    parser_id: str
    parser_warnings: list[str] = []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_import_parsers_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/services/import_parsers/schema.py tests/test_import_parsers_schema.py
git commit -m "feat: add row schemas for duty_locations/hierarchy/duty_types/exemption_types import sheets"
```

---

## Task 2: Parser — `duty_locations` and `exemption_types` sheets (no cross-refs)

**Files:**
- Modify: `backend/app/services/import_parsers/v1_standard.py`
- Test: `backend/tests/test_import_parser_v1_config_sheets.py` (new)

**Interfaces:**
- Consumes: `ImportDutyLocationRow`, `ImportExemptionTypeRow`, `_sheet_rows()`, `_parse_bool` (from Task 1 / existing file).
- Produces: `V1StandardParser.parse()` populates `ParsedImportData.duty_locations` and `.exemption_types`. `KNOWN_SHEETS` includes `"duty_locations"` and `"exemption_types"`.

Note: `exemption_types.applies_to_duty_type_names` is a plain comma-split (no per-entry validation at parse time — validation happens at resolve time in Task 5) so this task has no cross-sheet dependency and can be done before the `hierarchy`/`duty_types` sheets (Task 3/4).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_import_parser_v1_config_sheets.py
from __future__ import annotations

import openpyxl

import app.services.import_parsers.v1_standard  # noqa: F401 (registers parser)
from app.services.import_parsers.registry import get_parser


def _wb(sheets: dict[str, list[list]]) -> openpyxl.Workbook:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    return wb


def test_parses_duty_locations_sheet():
    wb = _wb({
        "duty_locations": [
            ["name", "base", "active"],
            ["שער ראשי", "בסיס א", "true"],
        ],
    })
    data = get_parser("v1_standard").parse(wb)
    assert len(data.duty_locations) == 1
    row = data.duty_locations[0]
    assert row.name == "שער ראשי"
    assert row.base == "בסיס א"
    assert row.active is True


def test_parses_exemption_types_sheet_with_applies_to_list():
    wb = _wb({
        "exemption_types": [
            ["name", "description", "is_global", "is_medical", "is_commander_exemption", "applies_to_duty_types"],
            ["פטור רפואי", "תיאור", "false", "true", "false", "שמירה, מטבח"],
        ],
    })
    data = get_parser("v1_standard").parse(wb)
    assert len(data.exemption_types) == 1
    row = data.exemption_types[0]
    assert row.name == "פטור רפואי"
    assert row.is_medical is True
    assert row.applies_to_duty_type_names == ["שמירה", "מטבח"]


def test_absent_sheets_yield_empty_lists():
    wb = _wb({})
    data = get_parser("v1_standard").parse(wb)
    assert data.duty_locations == []
    assert data.exemption_types == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_import_parser_v1_config_sheets.py -v`
Expected: FAIL — `parse()` doesn't yet read these sheets, `data.duty_locations`/`.exemption_types` stay `[]` even when sheet has rows (first two tests fail).

- [ ] **Step 3: Implement parsing**

In `backend/app/services/import_parsers/v1_standard.py`:

1. Update imports:

```python
from app.services.import_parsers.schema import (
    ImportDutyShiftRow,
    ImportExemptionTypeRow,
    ImportDutyLocationRow,
    ImportNodeQuota,
    ImportSoldierRow,
    ParsedImportData,
)
```

2. Update `KNOWN_SHEETS`:

```python
KNOWN_SHEETS = {"soldiers", "duty_shifts", "assignments", "duty_locations", "hierarchy", "duty_types", "exemption_types"}
```

3. Add a small helper for comma-separated name lists (used by `exemption_types.applies_to_duty_types` here, and by `duty_types.eligible_units` in Task 4):

```python
def _parse_name_list(raw) -> list[str]:
    s = str(raw or "").strip()
    if not s:
        return []
    return [part.strip() for part in s.split(",") if part.strip()]
```

4. In `V1StandardParser.parse()`, add (alongside the existing `soldiers`/`duty_shifts` blocks, before the final `return ParsedImportData(...)`):

```python
        duty_locations = [
            ImportDutyLocationRow(
                source_row=r["_row"],
                name=str(r.get("name") or "").strip(),
                base=str(r.get("base") or "").strip() or None,
                active=_parse_bool(r.get("active")),
            )
            for r in _sheet_rows(wb, "duty_locations")
        ]

        exemption_types = [
            ImportExemptionTypeRow(
                source_row=r["_row"],
                name=str(r.get("name") or "").strip(),
                description=str(r.get("description") or "").strip() or None,
                is_global=_parse_bool(r.get("is_global")),
                is_medical=_parse_bool(r.get("is_medical")),
                is_commander_exemption=_parse_bool(r.get("is_commander_exemption")),
                applies_to_duty_type_names=_parse_name_list(r.get("applies_to_duty_types")),
            )
            for r in _sheet_rows(wb, "exemption_types")
        ]
```

5. Update the final return statement to pass these through:

```python
        return ParsedImportData(
            soldiers=soldiers,
            duty_shifts=duty_shifts,
            duty_locations=duty_locations,
            exemption_types=exemption_types,
            parser_id=self.id,
            parser_warnings=warnings,
        )
```

(`hierarchy=` and `duty_types=` are added in Task 3/4 — `ParsedImportData` defaults them to `[]` in the meantime, so this compiles and the new tests for this task pass.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_import_parser_v1_config_sheets.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/services/import_parsers/v1_standard.py tests/test_import_parser_v1_config_sheets.py
git commit -m "feat: parse duty_locations and exemption_types import sheets"
```

---

## Task 3: Parser — `hierarchy` sheet

**Files:**
- Modify: `backend/app/services/import_parsers/v1_standard.py`
- Modify: `backend/tests/test_import_parser_v1_config_sheets.py`

**Interfaces:**
- Consumes: `ImportHierarchyNodeRow` (Task 1), `_sheet_rows()`.
- Produces: `V1StandardParser.parse()` populates `ParsedImportData.hierarchy`. New helper `_parse_duty_manager_refs(raw, source_row) -> tuple[list[str], list[str]]` (value list + warnings), same shape as `_parse_node_quotas`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_import_parser_v1_config_sheets.py`:

```python
def test_parses_hierarchy_sheet_with_duty_managers():
    wb = _wb({
        "hierarchy": [
            ["name", "level", "parent_name", "commander_personal_number", "commander_name", "duty_managers"],
            ["מדור א", "group", "יחידה ראשית", "12345", "ישראל ישראלי", "12345:ישראל ישראלי;23456:משה כהן"],
        ],
    })
    data = get_parser("v1_standard").parse(wb)
    assert len(data.hierarchy) == 1
    row = data.hierarchy[0]
    assert row.name == "מדור א"
    assert row.level == "group"
    assert row.parent_name == "יחידה ראשית"
    assert row.commander_personal_number == "12345"
    assert row.commander_name == "ישראל ישראלי"
    assert row.duty_manager_refs == ["12345:ישראל ישראלי", "23456:משה כהן"]


def test_hierarchy_malformed_duty_manager_entry_produces_warning_not_error():
    wb = _wb({
        "hierarchy": [
            ["name", "level", "parent_name", "commander_personal_number", "commander_name", "duty_managers"],
            ["מדור ב", "group", "", "", "", "not-a-valid-entry"],
        ],
    })
    data = get_parser("v1_standard").parse(wb)
    assert data.hierarchy[0].duty_manager_refs == []
    assert any("מדור ב" in w or "שורה 2" in w for w in data.parser_warnings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_import_parser_v1_config_sheets.py -v`
Expected: FAIL — `data.hierarchy` stays `[]`.

- [ ] **Step 3: Implement parsing**

In `backend/app/services/import_parsers/v1_standard.py`:

1. Add `ImportHierarchyNodeRow` to the schema import block.

2. Add the ref-list parser near `_parse_node_quotas`:

```python
def _parse_duty_manager_refs(raw, source_row: int) -> tuple[list[str], list[str]]:
    """Parse `personal_number:full_name;personal_number:full_name` into a list
    of raw `"pn:name"` strings (resolved later against real soldiers) — same
    `;`-then-`:` convention as `_parse_node_quotas`. Malformed entries (missing
    colon) produce a row-tagged warning and are skipped individually."""
    s = str(raw or "").strip()
    if not s:
        return [], []
    refs: list[str] = []
    warnings: list[str] = []
    for part in s.split(";"):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            warnings.append(
                f"שורה {source_row}: ערך אחראי תורנות שגוי '{part}' — הפורמט הנדרש הוא 'מספר_אישי:שם_מלא'"
            )
            continue
        refs.append(part)
    return refs, warnings
```

3. In `parse()`, add (the two-pass parent/commander *resolution* happens later in `import_sessions.py` — this stage only extracts raw cell values):

```python
        hierarchy = []
        for r in _sheet_rows(wb, "hierarchy"):
            dm_refs, dm_warnings = _parse_duty_manager_refs(r.get("duty_managers"), r["_row"])
            warnings.extend(dm_warnings)
            hierarchy.append(
                ImportHierarchyNodeRow(
                    source_row=r["_row"],
                    name=str(r.get("name") or "").strip(),
                    level=str(r.get("level") or "").strip(),
                    parent_name=str(r.get("parent_name") or "").strip() or None,
                    commander_personal_number=str(r.get("commander_personal_number") or "").strip() or None,
                    commander_name=str(r.get("commander_name") or "").strip() or None,
                    duty_manager_refs=dm_refs,
                )
            )
```

4. Add `hierarchy=hierarchy` to the `ParsedImportData(...)` return call.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_import_parser_v1_config_sheets.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/services/import_parsers/v1_standard.py tests/test_import_parser_v1_config_sheets.py
git commit -m "feat: parse hierarchy import sheet (name/level/parent/commander/duty-managers)"
```

---

## Task 4: Parser — `duty_types` sheet

**Files:**
- Modify: `backend/app/services/import_parsers/v1_standard.py`
- Modify: `backend/tests/test_import_parser_v1_config_sheets.py`

**Interfaces:**
- Consumes: `ImportDutyTypeRow` (Task 1), `_sheet_rows()`, `_parse_name_list()` (Task 2), `_parse_bool`, `_parse_date` (unused here) helpers.
- Produces: `V1StandardParser.parse()` populates `ParsedImportData.duty_types`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_import_parser_v1_config_sheets.py`:

```python
def test_parses_duty_types_sheet():
    wb = _wb({
        "duty_types": [
            [
                "name", "score_per_day", "description", "active", "reserve_ratio",
                "reserve_minimum", "is_external", "contact_name", "contact_phone",
                "start_time", "end_time", "instructions", "eligible_units", "requirements_json",
            ],
            [
                "שמירה", "1.50", "תיאור", "true", "0.200",
                "2", "false", "דני", "050-1234567",
                "20:00", "06:00", "הצטיידות", "מדור א, מדור ב", '{"min_rank": 1}',
            ],
        ],
    })
    data = get_parser("v1_standard").parse(wb)
    assert len(data.duty_types) == 1
    row = data.duty_types[0]
    assert row.name == "שמירה"
    assert row.score_per_day == "1.50"
    assert row.reserve_minimum == 2
    assert row.eligible_unit_names == ["מדור א", "מדור ב"]
    assert row.requirements_json == '{"min_rank": 1}'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_import_parser_v1_config_sheets.py -v`
Expected: FAIL — `data.duty_types` stays `[]`.

- [ ] **Step 3: Implement parsing**

In `backend/app/services/import_parsers/v1_standard.py`:

1. Add `ImportDutyTypeRow` to the schema import block.

2. In `parse()`, add:

```python
        duty_types = [
            ImportDutyTypeRow(
                source_row=r["_row"],
                name=str(r.get("name") or "").strip(),
                score_per_day=str(r.get("score_per_day") or "").strip(),
                description=str(r.get("description") or "").strip() or None,
                active=_parse_bool(r.get("active")),
                reserve_ratio=str(r.get("reserve_ratio") or "").strip() or None,
                reserve_minimum=int(r["reserve_minimum"]) if str(r.get("reserve_minimum") or "").strip() else None,
                is_external=_parse_bool(r.get("is_external")),
                contact_name=str(r.get("contact_name") or "").strip() or None,
                contact_phone=str(r.get("contact_phone") or "").strip() or None,
                start_time=str(r.get("start_time") or "").strip() or None,
                end_time=str(r.get("end_time") or "").strip() or None,
                instructions=str(r.get("instructions") or "").strip() or None,
                eligible_unit_names=_parse_name_list(r.get("eligible_units")),
                requirements_json=str(r.get("requirements_json") or "").strip() or None,
            )
            for r in _sheet_rows(wb, "duty_types")
        ]
```

3. Add `duty_types=duty_types` to the `ParsedImportData(...)` return call.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_import_parser_v1_config_sheets.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/services/import_parsers/v1_standard.py tests/test_import_parser_v1_config_sheets.py
git commit -m "feat: parse duty_types import sheet"
```

---

## Task 5: Resolver — `_resolve_duty_locations`

**Files:**
- Modify: `backend/app/services/import_sessions.py`
- Test: `backend/tests/test_import_sessions_resolvers.py` (new)

**Interfaces:**
- Consumes: `ParsedImportData.duty_locations` (Task 2), `DutyLocation` model.
- Produces: `_resolve_duty_locations(session: Session, data: ParsedImportData) -> list[dict]`. Each dict: `{"row", "action" ("new"|"update"), "errors", "name", "base", "active", "existing_id"}`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_import_sessions_resolvers.py
from __future__ import annotations

from app.db.models import DutyLocation
from app.services.import_parsers.schema import ImportDutyLocationRow, ParsedImportData
from app.services.import_sessions import _resolve_duty_locations


def test_resolve_duty_locations_new_and_update(app_session):
    existing = DutyLocation(name="שער קיים", base="בסיס א")
    app_session.add(existing)
    app_session.flush()

    data = ParsedImportData(
        parser_id="v1_standard",
        duty_locations=[
            ImportDutyLocationRow(source_row=2, name="שער קיים", base="בסיס ב", active=True),
            ImportDutyLocationRow(source_row=3, name="שער חדש", base=None, active=None),
        ],
    )
    result = _resolve_duty_locations(app_session, data)
    assert result[0]["action"] == "update"
    assert result[0]["existing_id"] == str(existing.id)
    assert result[1]["action"] == "new"
    assert result[1]["existing_id"] is None
```

Use the `app_session` fixture (from `backend/tests/conftest.py`, already used across the suite for a plain DB session without an HTTP client).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_import_sessions_resolvers.py -v`
Expected: FAIL — `ImportError: cannot import name '_resolve_duty_locations'`.

- [ ] **Step 3: Implement the resolver**

In `backend/app/services/import_sessions.py`, add near the top of the imports:

```python
from app.db.models import (
    DutyLocation,
    DutyShift,
    DutyType,
    HierarchyNode,
    ImportSession,
    Soldier,
)
```

(`DutyLocation` is already imported — no change needed there; it's listed for clarity of what Task 5 needs.)

Add the resolver function (placed after `_resolve_soldiers`, before `_resolve_duty_shifts`):

```python
def _resolve_duty_locations(session: Session, data: ParsedImportData) -> list[dict]:
    existing_by_name = {
        loc.name: loc for loc in session.execute(select(DutyLocation)).scalars()
    }
    out = []
    for row in data.duty_locations:
        errors: list[str] = []
        if not row.name:
            errors.append("חסר שם מיקום")
        existing = existing_by_name.get(row.name) if row.name else None
        action = "error" if errors else ("update" if existing else "new")
        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "name": row.name,
            "base": row.base,
            "active": row.active,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_import_sessions_resolvers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/services/import_sessions.py tests/test_import_sessions_resolvers.py
git commit -m "feat: resolve duty_locations import rows"
```

---

## Task 6: Resolver — `_resolve_hierarchy`

**Files:**
- Modify: `backend/app/services/import_sessions.py`
- Modify: `backend/tests/test_import_sessions_resolvers.py`

**Interfaces:**
- Consumes: `ParsedImportData.hierarchy` (Task 3), `HierarchyNode`, `HierarchyLevelType`, `Soldier`, `is_node_in_actor_scope` (existing import in this file).
- Produces: `_resolve_hierarchy(session, data, actor, node_by_name=None, node_by_row=None) -> list[dict]`. Each dict: `{"row", "action" ("new"|"update"|"error"|"out_of_scope"), "errors", "name", "level", "parent_name", "resolved_parent_id", "commander_personal_number", "commander_name", "resolved_commander_id", "duty_manager_refs": [{"ref": str, "resolved_soldier_id": str|None}], "existing_id"}`.

This is the most complex resolver — two-pass parent-name resolution, personal-number-then-name soldier lookup for commander and each duty-manager ref, and actor scope check.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_import_sessions_resolvers.py`:

```python
from app.db.models import HierarchyLevelType, Soldier
from app.services.import_parsers.schema import ImportHierarchyNodeRow
from app.services.import_sessions import _resolve_hierarchy
from tests.helpers import create_node, create_soldier


def _admin(app_session):
    return create_soldier(app_session, personal_number="admin-1", role="admin")


def test_resolve_hierarchy_parent_forward_reference(app_session):
    # "group" ranks below "unit" per the seeded HierarchyLevelType data.
    admin = _admin(app_session)
    data = ParsedImportData(
        parser_id="v1_standard",
        hierarchy=[
            ImportHierarchyNodeRow(source_row=2, name="ילד", level="group", parent_name="הורה"),
            ImportHierarchyNodeRow(source_row=3, name="הורה", level="unit"),
        ],
    )
    result = _resolve_hierarchy(app_session, data, admin)
    child = next(r for r in result if r["name"] == "ילד")
    parent = next(r for r in result if r["name"] == "הורה")
    assert child["action"] == "new"
    assert parent["action"] == "new"
    assert child["errors"] == []


def test_resolve_hierarchy_commander_personal_number_then_name_fallback(app_session):
    admin = _admin(app_session)
    soldier = create_soldier(app_session, personal_number="12345")  # full_name = "Test 12345"
    data = ParsedImportData(
        parser_id="v1_standard",
        hierarchy=[
            ImportHierarchyNodeRow(
                source_row=2, name="מדור א", level="group",
                commander_personal_number="not-found", commander_name="Test 12345",
            ),
        ],
    )
    result = _resolve_hierarchy(app_session, data, admin)
    assert result[0]["resolved_commander_id"] == str(soldier.id)
    assert result[0]["errors"] == []


def test_resolve_hierarchy_unresolvable_commander_is_row_error(app_session):
    admin = _admin(app_session)
    data = ParsedImportData(
        parser_id="v1_standard",
        hierarchy=[
            ImportHierarchyNodeRow(
                source_row=2, name="מדור א", level="group",
                commander_personal_number="ghost", commander_name="לא קיים",
            ),
        ],
    )
    result = _resolve_hierarchy(app_session, data, admin)
    assert result[0]["action"] == "error"
    assert result[0]["errors"]


def test_resolve_hierarchy_duty_manager_refs_resolved(app_session):
    admin = _admin(app_session)
    dm = create_soldier(app_session, personal_number="99999")
    data = ParsedImportData(
        parser_id="v1_standard",
        hierarchy=[
            ImportHierarchyNodeRow(
                source_row=2, name="מדור א", level="group",
                duty_manager_refs=["99999:Test 99999"],
            ),
        ],
    )
    result = _resolve_hierarchy(app_session, data, admin)
    assert result[0]["duty_manager_refs"] == [{"ref": "99999:Test 99999", "resolved_soldier_id": str(dm.id)}]


def test_resolve_hierarchy_out_of_scope_for_non_admin(app_session):
    root = create_node(app_session, level="corps", name="שורש אחר")
    dm = create_soldier(app_session, personal_number="dm-1", role="duty_manager", hierarchy_node_id=root.id)
    data = ParsedImportData(
        parser_id="v1_standard",
        hierarchy=[
            ImportHierarchyNodeRow(source_row=2, name="מחוץ לטווח", level="corps"),
        ],
    )
    result = _resolve_hierarchy(app_session, data, dm)
    assert result[0]["action"] == "out_of_scope"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_import_sessions_resolvers.py -v`
Expected: FAIL — `_resolve_hierarchy` doesn't exist.

- [ ] **Step 3: Implement the resolver**

In `backend/app/services/import_sessions.py`, add:

```python
from app.db.models import HierarchyLevelType


def _resolve_soldier_ref(
    personal_number: str | None,
    full_name: str | None,
    by_pn: dict[str, Soldier],
    by_name: dict[str, list[Soldier]],
) -> tuple[Soldier | None, str | None]:
    """personal-number-first, name-fallback soldier lookup shared by commander
    and duty-manager-ref resolution. Returns (soldier_or_None, error_or_None)."""
    if personal_number and personal_number in by_pn:
        return by_pn[personal_number], None
    if full_name:
        matches = by_name.get(full_name, [])
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return None, f"שם '{full_name}' מתאים ליותר מחייל אחד"
    return None, f"לא נמצא חייל (מספר אישי '{personal_number or ''}', שם '{full_name or ''}')"


def _resolve_hierarchy(
    session: Session,
    data: ParsedImportData,
    actor: Soldier,
    node_by_name: dict[str, str] | None = None,
    node_by_row: dict[str, str] | None = None,
) -> list[dict]:
    node_by_name = node_by_name or {}
    node_by_row = node_by_row or {}
    existing_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}
    valid_levels = {
        lt.key for lt in session.execute(select(HierarchyLevelType)).scalars()
    }
    by_pn = {s.personal_number: s for s in session.execute(select(Soldier)).scalars()}
    by_name: dict[str, list[Soldier]] = {}
    for s in by_pn.values():
        by_name.setdefault(s.full_name, []).append(s)

    # Pass 1: figure out each row's own resolved-or-new identity (name -> row index),
    # so pass 2 can resolve forward-referenced parents regardless of sheet order.
    row_by_name = {row.name: row for row in data.hierarchy}

    out = []
    for row in data.hierarchy:
        errors: list[str] = []

        if row.level not in valid_levels:
            errors.append(f"סוג יחידה לא מוכר '{row.level}'")

        existing = existing_by_name.get(row.name)

        resolved_parent_id = None
        if row.parent_name:
            row_key = f"hierarchy:{row.source_row}"
            mapped_id = node_by_row.get(row_key) or node_by_name.get(row.parent_name)
            if mapped_id:
                resolved_parent_id = mapped_id
            elif row.parent_name in existing_by_name:
                resolved_parent_id = str(existing_by_name[row.parent_name].id)
            elif row.parent_name in row_by_name:
                resolved_parent_id = None  # resolved to another *new* row by name at commit time
            else:
                errors.append(f"יחידת אב לא מזוהה '{row.parent_name}'")

        resolved_commander_id = None
        if row.commander_personal_number or row.commander_name:
            soldier, err = _resolve_soldier_ref(
                row.commander_personal_number, row.commander_name, by_pn, by_name
            )
            if soldier is not None:
                resolved_commander_id = str(soldier.id)
            else:
                errors.append(f"מפקד לא מזוהה: {err}")

        dm_results = []
        for ref in row.duty_manager_refs:
            pn, _, name = ref.partition(":")
            soldier, err = _resolve_soldier_ref(pn.strip(), name.strip(), by_pn, by_name)
            dm_results.append({
                "ref": ref,
                "resolved_soldier_id": str(soldier.id) if soldier is not None else None,
            })
            if soldier is None:
                errors.append(f"אחראי תורנות לא מזוהה: {err}")

        action: str
        if errors:
            action = "error"
        elif existing is not None:
            action = "update"
        else:
            action = "new"

        if action != "error" and existing is not None and actor.role != "admin":
            if not is_node_in_actor_scope(session=session, actor=actor, node_id=existing.id):
                action = "out_of_scope"
        elif action == "new" and actor.role != "admin" and resolved_parent_id:
            try:
                if not is_node_in_actor_scope(
                    session=session, actor=actor, node_id=uuid.UUID(resolved_parent_id)
                ):
                    action = "out_of_scope"
            except ValueError:
                pass
        elif action == "new" and actor.role != "admin" and not resolved_parent_id and not row.parent_name:
            # A brand-new root node: only admins may create root nodes via import.
            action = "out_of_scope"

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "name": row.name,
            "level": row.level,
            "parent_name": row.parent_name,
            "resolved_parent_id": resolved_parent_id,
            "commander_personal_number": row.commander_personal_number,
            "commander_name": row.commander_name,
            "resolved_commander_id": resolved_commander_id,
            "duty_manager_refs": dm_results,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_import_sessions_resolvers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/services/import_sessions.py tests/test_import_sessions_resolvers.py
git commit -m "feat: resolve hierarchy import rows (parent/commander/duty-manager lookup)"
```

---

## Task 7: Resolver — `_resolve_duty_types`

**Files:**
- Modify: `backend/app/services/import_sessions.py`
- Modify: `backend/tests/test_import_sessions_resolvers.py`

**Interfaces:**
- Consumes: `ParsedImportData.duty_types` (Task 4), `DutyType`, `HierarchyNode`.
- Produces: `_resolve_duty_types(session, data, node_by_name=None, node_by_row=None) -> list[dict]`. Each dict: `{"row", "action" ("new"|"update"|"error"), "errors", "name", ...scalar fields..., "resolved_eligible_node_ids": list[str], "requirements": dict|None, "existing_id"}`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_import_sessions_resolvers.py`:

```python
from decimal import Decimal

from app.services.import_parsers.schema import ImportDutyTypeRow
from app.services.import_sessions import _resolve_duty_types


def test_resolve_duty_types_eligible_units_resolved(app_session):
    node = create_node(app_session, level="group", name="מדור א")
    data = ParsedImportData(
        parser_id="v1_standard",
        duty_types=[
            ImportDutyTypeRow(
                source_row=2, name="שמירה", score_per_day="1.50",
                eligible_unit_names=["מדור א"],
            ),
        ],
    )
    result = _resolve_duty_types(app_session, data)
    assert result[0]["action"] == "new"
    assert result[0]["resolved_eligible_node_ids"] == [str(node.id)]


def test_resolve_duty_types_unresolved_eligible_unit_is_error(app_session):
    data = ParsedImportData(
        parser_id="v1_standard",
        duty_types=[
            ImportDutyTypeRow(source_row=2, name="שמירה", score_per_day="1.50", eligible_unit_names=["רפאים"]),
        ],
    )
    result = _resolve_duty_types(app_session, data)
    assert result[0]["action"] == "error"


def test_resolve_duty_types_invalid_json_is_error(app_session):
    data = ParsedImportData(
        parser_id="v1_standard",
        duty_types=[
            ImportDutyTypeRow(source_row=2, name="שמירה", score_per_day="1.50", requirements_json="{not json"),
        ],
    )
    result = _resolve_duty_types(app_session, data)
    assert result[0]["action"] == "error"


def test_resolve_duty_types_valid_json_parsed(app_session):
    data = ParsedImportData(
        parser_id="v1_standard",
        duty_types=[
            ImportDutyTypeRow(source_row=2, name="שמירה", score_per_day="1.50", requirements_json='{"min_rank": 1}'),
        ],
    )
    result = _resolve_duty_types(app_session, data)
    assert result[0]["requirements"] == {"min_rank": 1}


def test_resolve_duty_types_non_numeric_score_is_error(app_session):
    data = ParsedImportData(
        parser_id="v1_standard",
        duty_types=[ImportDutyTypeRow(source_row=2, name="שמירה", score_per_day="not-a-number")],
    )
    result = _resolve_duty_types(app_session, data)
    assert result[0]["action"] == "error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_import_sessions_resolvers.py -v`
Expected: FAIL — `_resolve_duty_types` doesn't exist.

- [ ] **Step 3: Implement the resolver**

In `backend/app/services/import_sessions.py`, add `import json` and `from decimal import Decimal` near the top, then:

```python
def _resolve_duty_types(
    session: Session,
    data: ParsedImportData,
    node_by_name: dict[str, str] | None = None,
    node_by_row: dict[str, str] | None = None,
) -> list[dict]:
    node_by_name = node_by_name or {}
    node_by_row = node_by_row or {}
    existing_by_name = {dt.name: dt for dt in session.execute(select(DutyType)).scalars()}
    nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}

    out = []
    for row in data.duty_types:
        errors: list[str] = []

        score_per_day: Decimal | None = None
        try:
            score_per_day = Decimal(row.score_per_day) if row.score_per_day else None
            if score_per_day is None:
                errors.append("חסר ניקוד ליום")
        except Exception:
            errors.append(f"ניקוד ליום לא תקין '{row.score_per_day}'")

        reserve_ratio: Decimal | None = None
        if row.reserve_ratio:
            try:
                reserve_ratio = Decimal(row.reserve_ratio)
            except Exception:
                errors.append(f"יחס רזרבה לא תקין '{row.reserve_ratio}'")

        requirements: dict | None = None
        if row.requirements_json:
            try:
                requirements = json.loads(row.requirements_json)
            except Exception as exc:
                errors.append(f"JSON לא תקין בעמודת requirements_json: {exc}")

        resolved_eligible_node_ids: list[str] = []
        for unit_name in row.eligible_unit_names:
            row_key = f"duty_types:{row.source_row}:{unit_name}"
            mapped_id = node_by_row.get(row_key) or node_by_name.get(unit_name)
            node = None
            if mapped_id:
                node = session.get(HierarchyNode, uuid.UUID(mapped_id))
            if node is None:
                node = nodes_by_name.get(unit_name)
            if node is None:
                errors.append(f"יחידה זכאית לא מזוהה '{unit_name}'")
            else:
                resolved_eligible_node_ids.append(str(node.id))

        existing = existing_by_name.get(row.name) if row.name else None
        action = "error" if errors else ("update" if existing else "new")

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "name": row.name,
            "score_per_day": str(score_per_day) if score_per_day is not None else None,
            "description": row.description,
            "active": row.active,
            "reserve_ratio": str(reserve_ratio) if reserve_ratio is not None else None,
            "reserve_minimum": row.reserve_minimum,
            "is_external": row.is_external,
            "contact_name": row.contact_name,
            "contact_phone": row.contact_phone,
            "start_time": row.start_time,
            "end_time": row.end_time,
            "instructions": row.instructions,
            "resolved_eligible_node_ids": resolved_eligible_node_ids,
            "requirements": requirements,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_import_sessions_resolvers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/services/import_sessions.py tests/test_import_sessions_resolvers.py
git commit -m "feat: resolve duty_types import rows (eligible units, requirements JSON)"
```

---

## Task 8: Resolver — `_resolve_exemption_types`, and wire all 4 into `_resolve_and_score`

**Files:**
- Modify: `backend/app/services/import_sessions.py`
- Modify: `backend/tests/test_import_sessions_resolvers.py`

**Interfaces:**
- Consumes: `ParsedImportData.exemption_types` (Task 2), `ExemptionType`, `DutyType`.
- Produces: `_resolve_exemption_types(session, data, dt_by_name=None, dt_by_row=None) -> list[dict]`. Each dict: `{"row", "action", "errors", "name", "description", "is_global", "is_medical", "is_commander_exemption", "resolved_duty_type_ids": list[str], "existing_id"}`.
- Also modifies `_resolve_and_score()` to call all 4 new resolvers and include them in its returned dict.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_import_sessions_resolvers.py`:

```python
from app.db.models import ExemptionType
from app.services.import_parsers.schema import ImportExemptionTypeRow
from app.services.import_sessions import _resolve_and_score, _resolve_exemption_types


def test_resolve_exemption_types_applies_to_resolved(app_session):
    dt = create_duty_type(app_session, name="שמירה", score_per_day=Decimal("1.00"))
    data = ParsedImportData(
        parser_id="v1_standard",
        exemption_types=[
            ImportExemptionTypeRow(source_row=2, name="פטור", applies_to_duty_type_names=["שמירה"]),
        ],
    )
    result = _resolve_exemption_types(app_session, data)
    assert result[0]["action"] == "new"
    assert result[0]["resolved_duty_type_ids"] == [str(dt.id)]


def test_resolve_exemption_types_unresolved_applies_to_is_error(app_session):
    data = ParsedImportData(
        parser_id="v1_standard",
        exemption_types=[
            ImportExemptionTypeRow(source_row=2, name="פטור", applies_to_duty_type_names=["לא קיים"]),
        ],
    )
    result = _resolve_exemption_types(app_session, data)
    assert result[0]["action"] == "error"


def test_resolve_and_score_includes_all_new_groups(app_session):
    admin = _admin(app_session)
    data = ParsedImportData(parser_id="v1_standard")
    result = _resolve_and_score(app_session, data, admin)
    assert set(result.keys()) >= {
        "soldiers", "duty_shifts", "shift_templates",
        "duty_locations", "hierarchy", "duty_types", "exemption_types",
        "parser_id", "parser_warnings",
    }
```

Add `from app.services.duty_config import create_duty_type` to the test file's imports (it's already used similarly in `test_import_sessions_api.py`).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_import_sessions_resolvers.py -v`
Expected: FAIL — `_resolve_exemption_types` doesn't exist, and `_resolve_and_score` doesn't return the new keys.

- [ ] **Step 3: Implement the resolver and wire it up**

In `backend/app/services/import_sessions.py`, add `ExemptionType` to the `app.db.models` import, then add:

```python
def _resolve_exemption_types(
    session: Session,
    data: ParsedImportData,
    dt_by_name: dict[str, str] | None = None,
    dt_by_row: dict[str, str] | None = None,
) -> list[dict]:
    dt_by_name = dt_by_name or {}
    dt_by_row = dt_by_row or {}
    existing_by_name = {et.name: et for et in session.execute(select(ExemptionType)).scalars()}
    duty_types_by_name = {dt.name: dt for dt in session.execute(select(DutyType)).scalars()}

    out = []
    for row in data.exemption_types:
        errors: list[str] = []
        if not row.name:
            errors.append("חסר שם פטור")

        resolved_duty_type_ids: list[str] = []
        for dt_name in row.applies_to_duty_type_names:
            row_key = f"exemption_types:{row.source_row}:{dt_name}"
            mapped_id = dt_by_row.get(row_key) or dt_by_name.get(dt_name)
            dt = None
            if mapped_id:
                dt = session.get(DutyType, uuid.UUID(mapped_id))
            if dt is None:
                dt = duty_types_by_name.get(dt_name)
            if dt is None:
                errors.append(f"סוג תורנות לא מזוהה '{dt_name}'")
            else:
                resolved_duty_type_ids.append(str(dt.id))

        existing = existing_by_name.get(row.name) if row.name else None
        action = "error" if errors else ("update" if existing else "new")

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "name": row.name,
            "description": row.description,
            "is_global": row.is_global,
            "is_medical": row.is_medical,
            "is_commander_exemption": row.is_commander_exemption,
            "resolved_duty_type_ids": resolved_duty_type_ids,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out
```

Then update `_resolve_and_score()` to:

```python
def _resolve_and_score(
    session: Session,
    data: ParsedImportData,
    actor: Soldier,
    selections: dict | None = None,
) -> dict:
    nm = (selections or {}).get("_name_mappings", {})
    dt_by_name  = nm.get("duty_type", {}).get("by_name", {})
    dt_by_row   = nm.get("duty_type", {}).get("by_row", {})
    node_by_name = nm.get("hierarchy_node", {}).get("by_name", {})
    node_by_row  = nm.get("hierarchy_node", {}).get("by_row", {})
    return {
        "soldiers": _resolve_soldiers(session, data, actor, node_by_name, node_by_row),
        "duty_shifts": _resolve_duty_shifts(session, data, actor, dt_by_name, dt_by_row, node_by_name, node_by_row),
        "shift_templates": _resolve_shift_templates(session, data, dt_by_name, dt_by_row),
        "duty_locations": _resolve_duty_locations(session, data),
        "hierarchy": _resolve_hierarchy(session, data, actor, node_by_name, node_by_row),
        "duty_types": _resolve_duty_types(session, data, node_by_name, node_by_row),
        "exemption_types": _resolve_exemption_types(session, data, dt_by_name, dt_by_row),
        "parser_id": data.parser_id,
        "parser_warnings": data.parser_warnings,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_import_sessions_resolvers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/services/import_sessions.py tests/test_import_sessions_resolvers.py
git commit -m "feat: resolve exemption_types import rows and wire all 4 new sheets into resolve_and_score"
```

---

## Task 9: Commit logic — `duty_locations` and `duty_types`

**Files:**
- Modify: `backend/app/services/import_sessions.py`
- Test: `backend/tests/integration/test_import_sessions_config_confirm.py` (new)

**Interfaces:**
- Consumes: resolver output dicts from Tasks 5 and 7; `create_location`/`update_location`, `create_duty_type`/`update_duty_type` from `app.services.duty_config`.
- Produces: `confirm_session()` applies `duty_locations` and `duty_types` groups, extending `created`/`updated`/`skipped` counts and `import_session.created_links`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_import_sessions_config_confirm.py
from __future__ import annotations

import io
import uuid
from decimal import Decimal

import openpyxl

import app.services.import_parsers.v1_standard  # noqa: F401
from app.db.models import DutyLocation, DutyType
from app.services.duty_config import create_duty_type
from tests.helpers import auth_headers, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _token(soldier) -> str:
    return auth_headers(soldier)["Authorization"].split(" ", 1)[1]


def _wb(sheets: dict[str, list[list]]) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload(client, token, xlsx: bytes):
    return client.post(
        "/api/import/sessions?parser_id=v1_standard",
        files={"file": ("import.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"Authorization": f"Bearer {token}"},
    )


def test_confirm_creates_duty_location_and_duty_type(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    name = f"שמירה_{_uid()}"
    loc_name = f"שער_{_uid()}"
    xlsx = _wb({
        "duty_locations": [["name", "base", "active"], [loc_name, "בסיס א", "true"]],
        "duty_types": [
            ["name", "score_per_day", "description", "active", "reserve_ratio", "reserve_minimum",
             "is_external", "contact_name", "contact_phone", "start_time", "end_time",
             "instructions", "eligible_units", "requirements_json"],
            [name, "1.50", "", "true", "0.000", "0", "false", "", "", "", "", "", "", ""],
        ],
    })
    resp = _upload(client, _token(admin), xlsx)
    session_id = resp.json()["session_id"]

    confirmed = client.post(
        f"/api/import/sessions/{session_id}/confirm",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["created"] == 2
    assert body["errors"] == []

    assert admin_session.query(DutyLocation).filter_by(name=loc_name).one()
    dt = admin_session.query(DutyType).filter_by(name=name).one()
    assert dt.score_per_day == Decimal("1.50")


def test_confirm_updates_existing_duty_location(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    loc = DutyLocation(name=f"שער_{_uid()}", base="ישן")
    admin_session.add(loc)
    admin_session.commit()

    xlsx = _wb({"duty_locations": [["name", "base", "active"], [loc.name, "חדש", "true"]]})
    resp = _upload(client, _token(admin), xlsx)
    session_id = resp.json()["session_id"]

    confirmed = client.post(
        f"/api/import/sessions/{session_id}/confirm",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["updated"] == 1
    admin_session.refresh(loc)
    assert loc.base == "חדש"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_import_sessions_config_confirm.py -v`
Expected: FAIL — `confirm_session` doesn't apply `duty_locations`/`duty_types` yet, so counts are `0` and the DB rows don't exist.

- [ ] **Step 3: Implement commit logic**

In `backend/app/services/import_sessions.py`, add imports:

```python
from app.services.duty_config import (
    create_duty_type,
    create_location,
    update_duty_type,
    update_location,
)
```

In `confirm_session()`, after the existing `# ── Duty shifts ──` block and before `import_session.created_links = {...}`, add:

```python
    # ── Duty locations ─────────────────────────────────────────────────
    for row in state.get("duty_locations", []):
        effective = _effective_action(selections, "duty_locations", row)
        if row["action"] == "error" or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                if effective == "new":
                    create_location(
                        session, name=row["name"], base=row.get("base"), actor_id=actor.id,
                    )
                    created += 1
                elif effective == "update" and row.get("existing_id"):
                    loc = session.get(DutyLocation, uuid.UUID(row["existing_id"]))
                    if loc is not None:
                        update_location(
                            session, location=loc, name=None, base=row.get("base"), actor_id=actor.id,
                        )
                        if row.get("active") is not None:
                            loc.active = row["active"]
                        updated += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "duty_locations", "error": str(exc)})

    # ── Duty types ──────────────────────────────────────────────────────
    for row in state.get("duty_types", []):
        effective = _effective_action(selections, "duty_types", row)
        if row["action"] == "error" or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                eligible_ids = [uuid.UUID(nid) for nid in row.get("resolved_eligible_node_ids", [])] or None
                if effective == "new":
                    create_duty_type(
                        session,
                        name=row["name"],
                        score_per_day=Decimal(row["score_per_day"]),
                        description=row.get("description"),
                        reserve_ratio=Decimal(row["reserve_ratio"]) if row.get("reserve_ratio") else Decimal("0.000"),
                        reserve_minimum=row.get("reserve_minimum") or 0,
                        contact_name=row.get("contact_name"),
                        contact_phone=row.get("contact_phone"),
                        instructions=row.get("instructions"),
                        is_external=bool(row.get("is_external")),
                        eligible_node_ids=eligible_ids,
                        actor_id=actor.id,
                    )
                    created += 1
                elif effective == "update" and row.get("existing_id"):
                    dt = session.get(DutyType, uuid.UUID(row["existing_id"]))
                    if dt is not None:
                        update_duty_type(
                            session,
                            duty_type=dt,
                            name=None,
                            score_per_day=Decimal(row["score_per_day"]) if row.get("score_per_day") else None,
                            description=row.get("description"),
                            reserve_ratio=Decimal(row["reserve_ratio"]) if row.get("reserve_ratio") else None,
                            reserve_minimum=row.get("reserve_minimum"),
                            contact_name=row.get("contact_name"),
                            contact_phone=row.get("contact_phone"),
                            instructions=row.get("instructions"),
                            is_external=row.get("is_external"),
                            eligible_node_ids=eligible_ids if row.get("resolved_eligible_node_ids") else ...,
                            requirements=row.get("requirements"),
                            actor_id=actor.id,
                        )
                        if row.get("active") is not None:
                            dt.active = row["active"]
                        updated += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "duty_types", "error": str(exc)})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_import_sessions_config_confirm.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/services/import_sessions.py tests/integration/test_import_sessions_config_confirm.py
git commit -m "feat: commit duty_locations and duty_types import rows"
```

---

## Task 10: Commit logic — `hierarchy` (incl. duty manager scope diffing) and `exemption_types`

**Files:**
- Modify: `backend/app/services/import_sessions.py`
- Modify: `backend/tests/integration/test_import_sessions_config_confirm.py`

**Interfaces:**
- Consumes: resolver output from Tasks 6 and 8; `create_node`, `set_commander`, `move_node`, `change_node_level` from `app.services.hierarchy`; `assign_dm_scope`, `remove_dm_scope` from `app.services.dm_scope`; `create_exemption_type`, `update_exemption_type`, `set_exemption_duty_types` from `app.services.duty_config`.
- Produces: `confirm_session()` applies `hierarchy` and `exemption_types` groups.

Hierarchy rows are applied in **two sub-passes**: first create/update every node's own fields (so every row has a real `id`), then a second sub-pass resolves any `parent_name` that pointed at another *new* row in the same sheet (which had no id during resolution) and applies it via `move_node`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/integration/test_import_sessions_config_confirm.py`:

```python
from app.db.models import DutyManagerScope, ExemptionDutyTypeMap, ExemptionType, HierarchyNode


def test_confirm_creates_hierarchy_node_with_commander_and_duty_manager(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    commander = create_soldier(admin_session, personal_number=f"cmd_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}")
    node_name = f"מדור_{_uid()}"

    xlsx = _wb({
        "hierarchy": [
            ["name", "level", "parent_name", "commander_personal_number", "commander_name", "duty_managers"],
            [node_name, "group", "", commander.personal_number, "", f"{dm.personal_number}:{dm.full_name}"],
        ],
    })
    resp = _upload(client, _token(admin), xlsx)
    session_id = resp.json()["session_id"]

    confirmed = client.post(
        f"/api/import/sessions/{session_id}/confirm",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["created"] == 1

    node = admin_session.query(HierarchyNode).filter_by(name=node_name).one()
    assert node.commander_id == commander.id
    scope = admin_session.query(DutyManagerScope).filter_by(hierarchy_node_id=node.id).one()
    assert scope.duty_manager_id == dm.id


def test_confirm_creates_exemption_type_with_applies_to(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    et_name = f"פטור_{_uid()}"

    xlsx = _wb({
        "exemption_types": [
            ["name", "description", "is_global", "is_medical", "is_commander_exemption", "applies_to_duty_types"],
            [et_name, "", "false", "true", "false", dt.name],
        ],
    })
    resp = _upload(client, _token(admin), xlsx)
    session_id = resp.json()["session_id"]

    confirmed = client.post(
        f"/api/import/sessions/{session_id}/confirm",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["created"] == 1

    et = admin_session.query(ExemptionType).filter_by(name=et_name).one()
    m = admin_session.query(ExemptionDutyTypeMap).filter_by(exemption_type_id=et.id).one()
    assert m.duty_type_id == dt.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_import_sessions_config_confirm.py -v`
Expected: FAIL — `confirm_session` doesn't apply `hierarchy`/`exemption_types` yet.

- [ ] **Step 3: Implement commit logic**

In `backend/app/services/import_sessions.py`, add imports:

```python
from app.services.dm_scope import assign_dm_scope, remove_dm_scope
from app.services.duty_config import (
    create_duty_type,
    create_exemption_type,
    create_location,
    set_exemption_duty_types,
    update_duty_type,
    update_exemption_type,
    update_location,
)
from app.services.hierarchy import change_node_level, create_node, move_node, set_commander
```

In `confirm_session()`, add (placed after the `duty_types` block from Task 9):

```python
    # ── Hierarchy ───────────────────────────────────────────────────────
    name_to_new_node_id: dict[str, uuid.UUID] = {}
    for row in state.get("hierarchy", []):
        effective = _effective_action(selections, "hierarchy", row)
        if row["action"] in ("error", "out_of_scope") or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                if effective == "new":
                    parent_id = (
                        uuid.UUID(row["resolved_parent_id"]) if row.get("resolved_parent_id") else None
                    )
                    node = create_node(
                        session,
                        level=row["level"],
                        name=row["name"],
                        parent_id=parent_id,
                        commander_id=(
                            uuid.UUID(row["resolved_commander_id"])
                            if row.get("resolved_commander_id") else None
                        ),
                        actor_id=actor.id,
                    )
                    name_to_new_node_id[row["name"]] = node.id
                    for dm in row.get("duty_manager_refs", []):
                        if dm.get("resolved_soldier_id"):
                            assign_dm_scope(
                                session, soldier_id=uuid.UUID(dm["resolved_soldier_id"]),
                                node_id=node.id, actor_id=actor.id,
                            )
                    created += 1
                elif effective == "update" and row.get("existing_id"):
                    node = session.get(HierarchyNode, uuid.UUID(row["existing_id"]))
                    if node is not None:
                        if row.get("level") and row["level"] != node.level:
                            change_node_level(session, node_id=node.id, level=row["level"], actor_id=actor.id)
                        if row.get("resolved_parent_id") and uuid.UUID(row["resolved_parent_id"]) != node.parent_id:
                            move_node(session, node_id=node.id, new_parent_id=uuid.UUID(row["resolved_parent_id"]), actor_id=actor.id)
                        if row.get("resolved_commander_id") is not None:
                            set_commander(
                                session, node_id=node.id,
                                commander_id=uuid.UUID(row["resolved_commander_id"]), actor_id=actor.id,
                            )
                        existing_scopes = {
                            s.duty_manager_id: s.id
                            for s in session.execute(
                                select(DutyManagerScope).where(DutyManagerScope.hierarchy_node_id == node.id)
                            ).scalars()
                        }
                        desired_ids = {
                            uuid.UUID(dm["resolved_soldier_id"])
                            for dm in row.get("duty_manager_refs", [])
                            if dm.get("resolved_soldier_id")
                        }
                        for soldier_id in desired_ids - set(existing_scopes.keys()):
                            assign_dm_scope(session, soldier_id=soldier_id, node_id=node.id, actor_id=actor.id)
                        for soldier_id, scope_id in existing_scopes.items():
                            if soldier_id not in desired_ids:
                                remove_dm_scope(session, entry_id=scope_id, actor_id=actor.id)
                        updated += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "hierarchy", "error": str(exc)})

    # Second sub-pass: link any node whose parent_name pointed at another
    # *new* row in this same sheet (unresolvable during the resolve phase,
    # since that row had no id yet).
    for row in state.get("hierarchy", []):
        effective = _effective_action(selections, "hierarchy", row)
        if row["action"] in ("error", "out_of_scope") or effective != "new":
            continue
        if row.get("parent_name") and not row.get("resolved_parent_id") and row["parent_name"] in name_to_new_node_id:
            node_id = name_to_new_node_id.get(row["name"])
            parent_id = name_to_new_node_id[row["parent_name"]]
            if node_id is not None:
                try:
                    with session.begin_nested():
                        move_node(session, node_id=node_id, new_parent_id=parent_id, actor_id=actor.id)
                except Exception as exc:
                    errors.append({"row": row["row"], "type": "hierarchy", "error": str(exc)})

    # ── Exemption types ─────────────────────────────────────────────────
    for row in state.get("exemption_types", []):
        effective = _effective_action(selections, "exemption_types", row)
        if row["action"] == "error" or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                duty_type_ids = [uuid.UUID(i) for i in row.get("resolved_duty_type_ids", [])]
                if effective == "new":
                    et = create_exemption_type(
                        session,
                        name=row["name"],
                        description=row.get("description"),
                        is_global=bool(row.get("is_global")),
                        is_medical=bool(row.get("is_medical")),
                        is_commander_exemption=bool(row.get("is_commander_exemption")),
                        actor_id=actor.id,
                    )
                    if duty_type_ids:
                        set_exemption_duty_types(
                            session, exemption_type_id=et.id, duty_type_ids=duty_type_ids, actor_id=actor.id,
                        )
                    created += 1
                elif effective == "update" and row.get("existing_id"):
                    et = session.get(ExemptionType, uuid.UUID(row["existing_id"]))
                    if et is not None:
                        update_exemption_type(
                            session,
                            exemption_type=et,
                            name=None,
                            description=row.get("description"),
                            is_global=row.get("is_global"),
                            is_medical=row.get("is_medical"),
                            is_commander_exemption=row.get("is_commander_exemption"),
                            actor_id=actor.id,
                        )
                        set_exemption_duty_types(
                            session, exemption_type_id=et.id, duty_type_ids=duty_type_ids, actor_id=actor.id,
                        )
                        updated += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "exemption_types", "error": str(exc)})
```

Note: `DutyManagerScope` and `ExemptionType` need to be added to the `app.db.models` import at the top of the file if not already present.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_import_sessions_config_confirm.py -v`
Expected: PASS

- [ ] **Step 5: Run the full backend test suite to check for regressions**

Run: `cd backend && pytest -q`
Expected: PASS (no regressions in existing `soldiers`/`duty_shifts` import tests)

- [ ] **Step 6: Commit**

```bash
cd backend && git add app/services/import_sessions.py tests/integration/test_import_sessions_config_confirm.py
git commit -m "feat: commit hierarchy and exemption_types import rows (dm-scope diffing, forward-parent linking)"
```

---

## Task 11: Session summary counts

**Files:**
- Modify: `backend/app/routes/import_sessions.py`
- Test: `backend/tests/integration/test_import_sessions_config_confirm.py`

**Interfaces:**
- Modifies `_session_summary()` to include row counts for the 4 new groups (used by the sessions-list UI).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/integration/test_import_sessions_config_confirm.py`:

```python
def test_session_summary_includes_new_group_counts(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    xlsx = _wb({"duty_locations": [["name", "base", "active"], [f"שער_{_uid()}", "", "true"]]})
    resp = _upload(client, _token(admin), xlsx)
    session_id = resp.json()["session_id"]

    listing = client.get(
        "/api/import/sessions", headers={"Authorization": f"Bearer {_token(admin)}"}
    ).json()
    entry = next(s for s in listing if s["id"] == session_id)
    assert entry["row_summary"]["duty_locations"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_import_sessions_config_confirm.py::test_session_summary_includes_new_group_counts -v`
Expected: FAIL — `KeyError: 'duty_locations'`.

- [ ] **Step 3: Implement**

In `backend/app/routes/import_sessions.py`, update `_session_summary()`:

```python
def _session_summary(sess: ImportSession) -> dict[str, Any]:
    state = sess.parsed_state or {}
    return {
        "id": str(sess.id),
        "status": sess.status,
        "filename": sess.filename,
        "created_at": sess.created_at.isoformat() if sess.created_at else None,
        "row_summary": {
            "soldiers": len(state.get("soldiers", [])),
            "duty_shifts": len(state.get("duty_shifts", [])),
            "duty_locations": len(state.get("duty_locations", [])),
            "hierarchy": len(state.get("hierarchy", [])),
            "duty_types": len(state.get("duty_types", [])),
            "exemption_types": len(state.get("exemption_types", [])),
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_import_sessions_config_confirm.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/routes/import_sessions.py tests/integration/test_import_sessions_config_confirm.py
git commit -m "feat: include new sheet groups in import session row_summary"
```

---

## Task 12: Backend export endpoint `GET /config/export`

**Files:**
- Create: `backend/app/routes/config_export.py`
- Modify: `backend/app/main.py` (register router)
- Test: `backend/tests/integration/test_config_export.py` (new)

**Interfaces:**
- Produces: `GET /api/config/export?sheets=duty_types,duty_locations,hierarchy,exemption_types` → `StreamingResponse` xlsx. `sheets` optional, defaults to all four.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_config_export.py
from __future__ import annotations

import io
import uuid
from decimal import Decimal

import openpyxl

from app.db.models import DutyLocation
from app.services.duty_config import create_duty_type, create_exemption_type, set_exemption_duty_types
from app.services.hierarchy import create_node, set_commander
from tests.helpers import auth_headers, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _token(soldier) -> str:
    return auth_headers(soldier)["Authorization"].split(" ", 1)[1]


def test_export_returns_only_requested_sheets(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    loc = DutyLocation(name=f"שער_{_uid()}")
    admin_session.add(loc)
    admin_session.commit()

    resp = client.get(
        "/api/config/export?sheets=duty_locations",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    assert resp.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert wb.sheetnames == ["duty_locations"]
    rows = list(wb["duty_locations"].iter_rows(min_row=2, values_only=True))
    assert any(r[0] == loc.name for r in rows)


def test_export_defaults_to_all_four_sheets(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    resp = client.get(
        "/api/config/export", headers={"Authorization": f"Bearer {_token(admin)}"}
    )
    assert resp.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert set(wb.sheetnames) == {"duty_types", "duty_locations", "hierarchy", "exemption_types"}


def test_export_hierarchy_includes_commander_and_duty_managers(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    commander = create_soldier(admin_session, personal_number=f"cmd_{_uid()}")
    node = create_node(admin_session, level="group", name=f"מדור_{_uid()}")
    set_commander(admin_session, node_id=node.id, commander_id=commander.id, actor_id=admin.id)
    admin_session.commit()

    resp = client.get(
        "/api/config/export?sheets=hierarchy", headers={"Authorization": f"Bearer {_token(admin)}"}
    )
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    rows = list(wb["hierarchy"].iter_rows(min_row=2, values_only=True))
    row = next(r for r in rows if r[0] == node.name)
    assert row[3] == commander.personal_number  # commander_personal_number column


def test_export_exemption_types_includes_applies_to(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    et = create_exemption_type(admin_session, name=f"et_{_uid()}")
    set_exemption_duty_types(admin_session, exemption_type_id=et.id, duty_type_ids=[dt.id])
    admin_session.commit()

    resp = client.get(
        "/api/config/export?sheets=exemption_types", headers={"Authorization": f"Bearer {_token(admin)}"}
    )
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    rows = list(wb["exemption_types"].iter_rows(min_row=2, values_only=True))
    row = next(r for r in rows if r[0] == et.name)
    assert dt.name in row[-1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_config_export.py -v`
Expected: FAIL — `404 Not Found` (route doesn't exist).

- [ ] **Step 3: Implement the endpoint**

Create `backend/app/routes/config_export.py`:

```python
from __future__ import annotations

import io
import json

import openpyxl
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_duty_manager_or_admin
from app.db.models import (
    DutyLocation,
    DutyManagerScope,
    DutyType,
    ExemptionDutyTypeMap,
    ExemptionType,
    HierarchyNode,
    Soldier,
)
from app.db.session import get_session

router = APIRouter(prefix="/config", tags=["config-export"])

ALL_SHEETS = ["duty_types", "duty_locations", "hierarchy", "exemption_types"]


def _write_duty_locations(wb: openpyxl.Workbook, session: Session) -> None:
    ws = wb.create_sheet("duty_locations")
    ws.append(["name", "base", "active"])
    for loc in session.execute(select(DutyLocation)).scalars():
        ws.append([loc.name, loc.base, loc.active])


def _write_hierarchy(wb: openpyxl.Workbook, session: Session) -> None:
    ws = wb.create_sheet("hierarchy")
    ws.append(["name", "level", "parent_name", "commander_personal_number", "commander_name", "duty_managers"])
    nodes = list(session.execute(select(HierarchyNode)).scalars())
    nodes_by_id = {n.id: n for n in nodes}
    soldier_ids = {n.commander_id for n in nodes if n.commander_id}
    dm_rows = list(session.execute(select(DutyManagerScope)).scalars())
    soldier_ids |= {r.duty_manager_id for r in dm_rows}
    soldiers_by_id = {
        s.id: s for s in session.execute(select(Soldier).where(Soldier.id.in_(soldier_ids))).scalars()
    } if soldier_ids else {}
    dm_by_node: dict = {}
    for r in dm_rows:
        dm_by_node.setdefault(r.hierarchy_node_id, []).append(r.duty_manager_id)

    for n in nodes:
        parent_name = nodes_by_id[n.parent_id].name if n.parent_id in nodes_by_id else ""
        commander = soldiers_by_id.get(n.commander_id) if n.commander_id else None
        dm_cell = ";".join(
            f"{soldiers_by_id[sid].personal_number}:{soldiers_by_id[sid].full_name}"
            for sid in dm_by_node.get(n.id, []) if sid in soldiers_by_id
        )
        ws.append([
            n.name, n.level, parent_name,
            commander.personal_number if commander else "",
            commander.full_name if commander else "",
            dm_cell,
        ])


def _write_duty_types(wb: openpyxl.Workbook, session: Session) -> None:
    ws = wb.create_sheet("duty_types")
    ws.append([
        "name", "score_per_day", "description", "active", "reserve_ratio", "reserve_minimum",
        "is_external", "contact_name", "contact_phone", "start_time", "end_time",
        "instructions", "eligible_units", "requirements_json",
    ])
    nodes_by_id = {n.id: n for n in session.execute(select(HierarchyNode)).scalars()}
    for dt in session.execute(select(DutyType)).scalars():
        eligible = ", ".join(
            nodes_by_id[nid].name for nid in (dt.eligible_node_ids or []) if nid in nodes_by_id
        )
        ws.append([
            dt.name, str(dt.score_per_day), dt.description, dt.active,
            str(dt.reserve_ratio), dt.reserve_minimum, dt.is_external,
            dt.contact_name, dt.contact_phone,
            dt.start_time.strftime("%H:%M") if dt.start_time else "",
            dt.end_time.strftime("%H:%M") if dt.end_time else "",
            dt.instructions, eligible, json.dumps(dt.requirements, ensure_ascii=False),
        ])


def _write_exemption_types(wb: openpyxl.Workbook, session: Session) -> None:
    ws = wb.create_sheet("exemption_types")
    ws.append(["name", "description", "is_global", "is_medical", "is_commander_exemption", "applies_to_duty_types"])
    duty_types_by_id = {dt.id: dt for dt in session.execute(select(DutyType)).scalars()}
    map_rows = list(session.execute(select(ExemptionDutyTypeMap)).scalars())
    applies_by_et: dict = {}
    for m in map_rows:
        applies_by_et.setdefault(m.exemption_type_id, []).append(m.duty_type_id)

    for et in session.execute(select(ExemptionType)).scalars():
        applies = ", ".join(
            duty_types_by_id[dtid].name
            for dtid in applies_by_et.get(et.id, []) if dtid in duty_types_by_id
        )
        ws.append([
            et.name, et.description, et.is_global, et.is_medical, et.is_commander_exemption, applies,
        ])


_WRITERS = {
    "duty_locations": _write_duty_locations,
    "hierarchy": _write_hierarchy,
    "duty_types": _write_duty_types,
    "exemption_types": _write_exemption_types,
}


@router.get("/export")
def export_config(
    sheets: str | None = None,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    requested = [s.strip() for s in sheets.split(",")] if sheets else ALL_SHEETS
    requested = [s for s in requested if s in _WRITERS]

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for sheet_name in requested:
        _WRITERS[sheet_name](wb, session)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="config_export.xlsx"'},
    )
```

In `backend/app/main.py`, add the import near the other route imports (e.g. next to `import_excel_routes`):

```python
from app.routes import config_export as config_export_routes
```

And register it in the `app.include_router(...)` block, next to `import_excel_routes`:

```python
    app.include_router(config_export_routes.router, prefix="/api")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_config_export.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/routes/config_export.py app/main.py tests/integration/test_config_export.py
git commit -m "feat: add GET /config/export endpoint for duty types/locations/hierarchy/exemptions"
```

---

## Task 13: Extend the import template download

**Files:**
- Modify: `backend/app/routes/import_excel.py`
- Test: `backend/tests/integration/test_import_template.py` (new)

**Interfaces:**
- Modifies `download_template()` to add 4 more example sheets.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_import_template.py
from __future__ import annotations

import io

import openpyxl

from tests.helpers import auth_headers, create_soldier


def test_template_includes_all_six_sheets(client, admin_session):
    admin = create_soldier(admin_session, personal_number="tmpl-admin", role="admin")
    token = auth_headers(admin)["Authorization"].split(" ", 1)[1]
    resp = client.get("/api/import/template", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert set(wb.sheetnames) >= {
        "soldiers", "duty_shifts", "duty_locations", "hierarchy", "duty_types", "exemption_types",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_import_template.py -v`
Expected: FAIL — only `soldiers`/`duty_shifts` present.

- [ ] **Step 3: Implement**

In `backend/app/routes/import_excel.py`, in `download_template()`, after the existing `ws_d.append(...)` example rows and before `buf = io.BytesIO()`, add:

```python
    ws_loc = wb.create_sheet("duty_locations")
    ws_loc.append(["name", "base", "active"])
    ws_loc.append(["שער ראשי", "בסיס א", "true"])
    ws_loc.append(["מטבח מרכזי", "בסיס א", "true"])

    ws_h = wb.create_sheet("hierarchy")
    ws_h.append(["name", "level", "parent_name", "commander_personal_number", "commander_name", "duty_managers"])
    ws_h.append(["אוגדה 1", "division", "", "", "", ""])
    ws_h.append(["מדור א", "group", "אוגדה 1", "12345", "ישראל ישראלי", "23456:משה כהן"])

    ws_dt = wb.create_sheet("duty_types")
    ws_dt.append([
        "name", "score_per_day", "description", "active", "reserve_ratio", "reserve_minimum",
        "is_external", "contact_name", "contact_phone", "start_time", "end_time",
        "instructions", "eligible_units", "requirements_json",
    ])
    ws_dt.append([
        "שמירה", "1.50", "שמירה בשער הראשי", "true", "0.200", "2",
        "false", "דני", "050-1234567", "20:00", "06:00",
        "הצטיידות במקלע", "מדור א", "{}",
    ])

    ws_et = wb.create_sheet("exemption_types")
    ws_et.append(["name", "description", "is_global", "is_medical", "is_commander_exemption", "applies_to_duty_types"])
    ws_et.append(["פטור רפואי", "אישור רופא", "false", "true", "false", "שמירה"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_import_template.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/routes/import_excel.py tests/integration/test_import_template.py
git commit -m "feat: extend import template with the 4 new config sheets"
```

---

## Task 14: Frontend — typed API wrappers for the new sheets

**Files:**
- Modify: `frontend/src/api/importSessions.ts`

**Interfaces:**
- Produces: TypeScript row types `DutyLocationRow`, `HierarchyImportRow`, `DutyTypeImportRow`, `ExemptionTypeImportRow` matching the resolver dict shapes from Tasks 5–8, added to `SessionDetail["parsed_state"]`.

- [ ] **Step 1: Locate and read the existing types**

Run: `grep -n "interface\|type.*Row" frontend/src/api/importSessions.ts`

(No test for this task — it's a pure type-definition change, verified by the frontend typecheck in Task 15/16's steps.)

- [ ] **Step 2: Add the new row interfaces**

In `frontend/src/api/importSessions.ts`, alongside the existing `SoldierRow`/`DutyShiftRow`-equivalent interfaces, add:

```typescript
export interface DutyLocationRow extends RowBase {
  name: string;
  base: string | null;
  active: boolean | null;
  existing_id: string | null;
}

export interface DutyManagerRefRow {
  ref: string;
  resolved_soldier_id: string | null;
}

export interface HierarchyImportRow extends RowBase {
  name: string;
  level: string;
  parent_name: string | null;
  resolved_parent_id: string | null;
  commander_personal_number: string | null;
  commander_name: string | null;
  resolved_commander_id: string | null;
  duty_manager_refs: DutyManagerRefRow[];
  existing_id: string | null;
}

export interface DutyTypeImportRow extends RowBase {
  name: string;
  score_per_day: string | null;
  resolved_eligible_node_ids: string[];
  requirements: Record<string, unknown> | null;
  existing_id: string | null;
}

export interface ExemptionTypeImportRow extends RowBase {
  name: string;
  resolved_duty_type_ids: string[];
  existing_id: string | null;
}
```

Then extend the `parsed_state` shape used by `SessionDetail` (find the interface/type that currently has `soldiers: SoldierRow[]; duty_shifts: DutyShiftRow[]; shift_templates: ShiftTemplateRow[]` and add):

```typescript
  duty_locations: DutyLocationRow[];
  hierarchy: HierarchyImportRow[];
  duty_types: DutyTypeImportRow[];
  exemption_types: ExemptionTypeImportRow[];
```

- [ ] **Step 3: Run the frontend typecheck**

Run: `cd frontend && npm run typecheck`
Expected: Errors pointing at `ImportSessionReviewPage.tsx` destructuring `detail.parsed_state` without the new fields being consumed — this is expected and resolved in Task 15/16. Confirm no errors *within* `importSessions.ts` itself.

- [ ] **Step 4: Commit**

```bash
cd frontend && git add src/api/importSessions.ts
git commit -m "feat: add typed row interfaces for the 4 new import sheets"
```

---

## Task 15: Frontend — review UI tabs for `duty_locations` and `hierarchy`

**Files:**
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`
- Modify: `frontend/src/pages/ImportSessionReviewPage.test.tsx`

**Interfaces:**
- Consumes: `DutyLocationRow`, `HierarchyImportRow` (Task 14).
- Produces: `TabKey` gains `"duty_locations" | "hierarchy"`; two new tab panels; `setRowAction`/`currentSelection` group unions extended.

- [ ] **Step 1: Write the failing test**

Read the existing `ImportSessionReviewPage.test.tsx` first to match its mocking style (`vi.mock("../api/importSessions", ...)`), then add:

```typescript
it("renders the duty_locations tab with row action controls", async () => {
  // Extend the mocked getSession() response's parsed_state with:
  // duty_locations: [{ row: 2, action: "new", name: "שער חדש", base: null, active: true, existing_id: null, errors: [] }]
  // ...render the page, click the "מיקומי תורנות" tab button, assert the row's name and an "אישור" action select appear.
});

it("renders the hierarchy tab showing commander and duty manager names", async () => {
  // Extend parsed_state.hierarchy: [{ row: 2, action: "new", name: "מדור א", level: "group",
  //   parent_name: null, resolved_parent_id: null, commander_personal_number: "12345",
  //   commander_name: "ישראל ישראלי", resolved_commander_id: "uuid-1",
  //   duty_manager_refs: [{ ref: "23456:משה כהן", resolved_soldier_id: "uuid-2" }],
  //   existing_id: null, errors: [] }]
  // ...render, click "היררכיה" tab, assert "מדור א" and "ישראל ישראלי" appear.
});
```

Write these two tests following the exact mock/render/assert pattern already used by the existing `soldiers`/`duty_shifts` tests in this file (reuse the same `renderPage()` helper and mock scaffolding already present).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/ImportSessionReviewPage.test.tsx`
Expected: FAIL — no "מיקומי תורנות"/"היררכיה" tab button exists yet.

- [ ] **Step 3: Implement the tabs**

In `frontend/src/pages/ImportSessionReviewPage.tsx`:

1. Update imports:

```typescript
import {
  type SessionDetail,
  type ConfirmSessionResult,
  type RowBase,
  type Selections,
  type ShiftTemplateRow,
  type DutyLocationRow,
  type HierarchyImportRow,
  getSession,
  reparseSession,
  saveSelections,
  confirmSession,
  listDutyTypesForImport,
  listNodesForImport,
} from "../api/importSessions";
```

2. Update `TabKey`:

```typescript
type TabKey = "soldiers" | "duty_shifts" | "shift_templates" | "duty_locations" | "hierarchy" | "duty_types" | "exemption_types";
```

3. Update the `setRowAction`/`currentSelection` group parameter unions to include all 7 group names (both functions currently type `group` as `"soldiers" | "duty_shifts" | "shift_templates"` — extend both to `"soldiers" | "duty_shifts" | "shift_templates" | "duty_locations" | "hierarchy" | "duty_types" | "exemption_types"`).

4. Destructure the new arrays where `soldiers`/`duty_shifts`/`shift_templates` are currently destructured from `detail.parsed_state` (two places — the loading guard section and the main render):

```typescript
  const { soldiers, duty_shifts, shift_templates, duty_locations, hierarchy, duty_types, exemption_types } = detail.parsed_state;
```

5. Add two entries to the tab-button list array:

```typescript
              ["duty_locations", `מיקומי תורנות (${duty_locations.length})`],
              ["hierarchy", `היררכיה (${hierarchy.length})`],
              ["duty_types", `סוגי תורנות (${duty_types.length})`],
              ["exemption_types", `פטורים (${exemption_types.length})`],
```

(placed after the existing `shift_templates` entry in the `[TabKey, string][]` array — `duty_types`/`exemption_types` panels are added in Task 16, but listing all 4 tab buttons together here is fine since an unmatched `tab === "duty_types"` branch simply doesn't render yet until Task 16 adds it.)

6. Add the `duty_locations` tab panel (after the existing `shift_templates` panel, before the `confirmError` block):

```tsx
        {tab === "duty_locations" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">שם</th>
                  <th className="text-right p-3">בסיס</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {duty_locations.map((row: DutyLocationRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">{row.name}</td>
                      <td className="p-3">{row.base}</td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("duty_locations", row)}
                              onChange={(e) => setRowAction("duty_locations", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {tab === "hierarchy" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">שם</th>
                  <th className="text-right p-3">סוג</th>
                  <th className="text-right p-3">יחידת אב</th>
                  <th className="text-right p-3">מפקד</th>
                  <th className="text-right p-3">אחראי תורנות</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {hierarchy.map((row: HierarchyImportRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">{row.name}</td>
                      <td className="p-3">{row.level}</td>
                      <td className="p-3">{row.parent_name ?? "—"}</td>
                      <td className="p-3">
                        {row.commander_personal_number || row.commander_name ? (
                          <span className={row.resolved_commander_id ? "" : "text-red-600"}>
                            {row.commander_name ?? row.commander_personal_number}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="p-3">
                        {row.duty_manager_refs.length === 0 ? (
                          "—"
                        ) : (
                          <div className="flex flex-col gap-0.5">
                            {row.duty_manager_refs.map((dm, i) => (
                              <span key={i} className={dm.resolved_soldier_id ? "" : "text-red-600"}>
                                {dm.ref}
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("hierarchy", row)}
                              onChange={(e) => setRowAction("hierarchy", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
```

Per the design's decision to reuse the existing picker for `parent_name` mismatches (same "hierarchy_node" kind already wired to `handlePick`/`buildPickerItems`), that affordance is added in Task 16 alongside the `duty_types`/`exemption_types` tabs' eligible-units/applies-to pickers, to keep this task's diff focused on the base table rendering. Until then, an unresolved `parent_name` simply shows as a row `error` (already true, since `_resolve_hierarchy` puts an unresolved parent into `errors`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/ImportSessionReviewPage.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd frontend && git add src/pages/ImportSessionReviewPage.tsx src/pages/ImportSessionReviewPage.test.tsx
git commit -m "feat: add duty_locations and hierarchy review tabs to import session UI"
```

---

## Task 16: Frontend — review UI tabs for `duty_types`/`exemption_types`, plus pickers for cross-references

**Files:**
- Modify: `frontend/src/api/importSessions.ts` (small addition)
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`
- Modify: `frontend/src/pages/ImportSessionReviewPage.test.tsx`

**Interfaces:**
- Consumes: `DutyTypeImportRow`, `ExemptionTypeImportRow` (Task 14).
- Produces: `duty_types`/`exemption_types` tab panels; `handlePick`'s `sameNameCount` computation extended to also scan `hierarchy` rows (for `parent_name`) and `duty_types`/`exemption_types` rows (for `eligible_unit`/`applies_to` names) so the existing picker infrastructure covers the new cross-references.

- [ ] **Step 1: Write the failing test**

Add to `ImportSessionReviewPage.test.tsx`:

```typescript
it("renders the duty_types tab and exemption_types tab", async () => {
  // Extend parsed_state.duty_types: [{ row: 2, action: "new", name: "שמירה", score_per_day: "1.50",
  //   resolved_eligible_node_ids: [], requirements: null, existing_id: null, errors: [] }]
  // Extend parsed_state.exemption_types: [{ row: 2, action: "new", name: "פטור",
  //   resolved_duty_type_ids: [], existing_id: null, errors: [] }]
  // render, click "סוגי תורנות" tab, assert "שמירה" appears; click "פטורים" tab, assert "פטור" appears.
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/ImportSessionReviewPage.test.tsx`
Expected: FAIL — no matching panel content for the new tabs.

- [ ] **Step 3: Implement**

1. Add the two remaining imports to the destructure/type import list (already added the `TabKey` variants and tab buttons in Task 15 — no change needed there).

2. Add the two tab panels (after the `hierarchy` panel from Task 15):

```tsx
        {tab === "duty_types" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">שם</th>
                  <th className="text-right p-3">ניקוד ליום</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {duty_types.map((row: DutyTypeImportRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">{row.name}</td>
                      <td className="p-3">{row.score_per_day}</td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("duty_types", row)}
                              onChange={(e) => setRowAction("duty_types", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {tab === "exemption_types" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">שם</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {exemption_types.map((row: ExemptionTypeImportRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">{row.name}</td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("exemption_types", row)}
                              onChange={(e) => setRowAction("exemption_types", row.row, e.target.value)}
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && <option value="skip">דלג</option>}
                            </select>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
```

Note: per the design, unresolved `eligible_unit`/`applies_to` names surface as row-level errors (shown via `StatusChip`'s `errors` list, already wired) — the same "pick a match" combobox affordance used for `hierarchy_node_name`/`duty_type_name` in the `soldiers`/`duty_shifts` tabs is deferred as a follow-up UI polish, not required for the feature to be usable end-to-end (a user can fix the source name in Excel and re-upload/reparse). This keeps this task's diff focused and avoids growing `handlePick`'s scope-counting logic across 4 more row shapes in the same change.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/ImportSessionReviewPage.test.tsx`
Expected: PASS

- [ ] **Step 5: Run the full frontend test suite and typecheck**

Run: `cd frontend && npm test && npm run typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd frontend && git add src/pages/ImportSessionReviewPage.tsx src/pages/ImportSessionReviewPage.test.tsx
git commit -m "feat: add duty_types and exemption_types review tabs to import session UI"
```

---

## Task 17: Frontend — unified export checkbox panel

**Files:**
- Modify: `frontend/src/components/ExcelExportButton.tsx` (extract shared helper)
- Modify: `frontend/src/pages/planning/ExportPage.tsx`
- Create/modify: `frontend/src/pages/planning/ExportPage.test.tsx`

**Interfaces:**
- Produces: `exportValueOf` exported from `ExcelExportButton.tsx` for reuse. `ExportPage` renders 6 checkboxes + one "ייצוא" button that builds one merged `.xlsx`.

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/pages/planning/ExportPage.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import ExportPage from "./ExportPage";

vi.mock("../../api/scoring", () => ({ getTransparency: vi.fn().mockResolvedValue({ rows: [] }) }));
vi.mock("../../api/hierarchy", () => ({ fetchFullTree: vi.fn().mockResolvedValue([]) }));

global.fetch = vi.fn().mockResolvedValue({
  ok: true,
  arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)),
});

describe("ExportPage", () => {
  it("renders one checkbox per exportable data type and a single export button", async () => {
    render(<ExportPage />);
    await waitFor(() => screen.getByText("ייצוא"));
    expect(screen.getByLabelText(/שקיפות/)).toBeInTheDocument();
    expect(screen.getByLabelText(/תתי-יחידות/)).toBeInTheDocument();
    expect(screen.getByLabelText(/סוגי תורנות/)).toBeInTheDocument();
    expect(screen.getByLabelText(/מיקומי תורנות/)).toBeInTheDocument();
    expect(screen.getByLabelText(/היררכיה/)).toBeInTheDocument();
    expect(screen.getByLabelText(/פטורים/)).toBeInTheDocument();
  });

  it("calls /config/export with only the checked config sheets when export is clicked", async () => {
    render(<ExportPage />);
    await waitFor(() => screen.getByText("ייצוא"));
    fireEvent.click(screen.getByLabelText(/סוגי תורנות/));
    fireEvent.click(screen.getByText("ייצוא"));
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/config/export?sheets=duty_types"),
        expect.anything(),
      );
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/planning/ExportPage.test.tsx`
Expected: FAIL — no checkboxes/single button exist yet (current page has 2 separate `ExcelExportButton`s, no checkboxes).

- [ ] **Step 3: Extract the shared cell-value helper**

In `frontend/src/components/ExcelExportButton.tsx`, change `exportValueOf` from a private function to an exported one (no logic change):

```typescript
export function exportValueOf<T>(col: ColDef<T>, row: T): string | number | boolean {
  const value = col.exportValue
    ? col.exportValue(row)
    : col.filterValue
      ? col.filterValue(row)
      : col.sortValue
        ? col.sortValue(row)
        : undefined;
  return value ?? "";
}
```

- [ ] **Step 4: Rewrite `ExportPage.tsx`**

Replace the `return (...)` JSX and add checkbox state, keeping the existing `flattenTree`/`dfsOrder`/`nodePath`/`SubRow` logic and `soldierCols`/`subCols` definitions untouched:

```tsx
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import * as XLSX from "xlsx";
import Layout from "../../components/Layout";
import { TransparencyRow, getTransparency } from "../../api/scoring";
import { fetchFullTree, NodeDTO } from "../../api/hierarchy";
import { exportValueOf } from "../../components/ExcelExportButton";
import type { ColDef } from "../../components/DataTable";

// ...(flattenTree, dfsOrder, nodePath, SubRow — unchanged)...

const CONFIG_SHEET_OPTIONS = [
  { key: "duty_types", label: "סוגי תורנות" },
  { key: "duty_locations", label: "מיקומי תורנות" },
  { key: "hierarchy", label: "היררכיה" },
  { key: "exemption_types", label: "פטורים" },
] as const;

export default function ExportPage() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<TransparencyRow[]>([]);
  const [treeNodes, setTreeNodes] = useState<NodeDTO[]>([]);
  const [checked, setChecked] = useState<Record<string, boolean>>({});

  useEffect(() => { void getTransparency().then((out) => setRows(out.rows)); }, []);
  useEffect(() => { void fetchFullTree().then(setTreeNodes); }, []);

  // ...(flatNodes, nodesById, nodeOrder, soldierRows, subRows, soldierCols, subCols — unchanged)...

  function toggle(key: string) {
    setChecked((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  async function handleExport() {
    const wb = XLSX.utils.book_new();

    if (checked.transparency) {
      const header = soldierCols.map((c) => c.header);
      const body = soldierRows.map((row) => soldierCols.map((c) => exportValueOf(c, row)));
      XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([header, ...body]), "transparency");
    }
    if (checked.sub_units) {
      const header = subCols.map((c) => c.header);
      const body = subRows.map((row) => subCols.map((c) => exportValueOf(c, row)));
      XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([header, ...body]), "sub_units");
    }

    const configSheets = CONFIG_SHEET_OPTIONS.filter((o) => checked[o.key]).map((o) => o.key);
    if (configSheets.length > 0) {
      const resp = await fetch(`/api/config/export?sheets=${configSheets.join(",")}`, {
        headers: { Authorization: `Bearer ${localStorage.getItem("token") ?? ""}` },
      });
      const buf = await resp.arrayBuffer();
      const configWb = XLSX.read(buf, { type: "array" });
      for (const name of configWb.SheetNames) {
        XLSX.utils.book_append_sheet(wb, configWb.Sheets[name], name);
      }
    }

    if (wb.SheetNames.length > 0) {
      XLSX.writeFile(wb, "export.xlsx");
    }
  }

  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4">
        <h2 className="text-xl font-semibold">{t("nav.planning_export")}</h2>
        <div className="space-y-2">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={!!checked.transparency} onChange={() => toggle("transparency")} />
            {t("export.transparency_title")}
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={!!checked.sub_units} onChange={() => toggle("sub_units")} />
            {t("export.sub_units_title")}
          </label>
          {CONFIG_SHEET_OPTIONS.map((o) => (
            <label key={o.key} className="flex items-center gap-2">
              <input type="checkbox" checked={!!checked[o.key]} onChange={() => toggle(o.key)} />
              {o.label}
            </label>
          ))}
        </div>
        <button
          type="button"
          className="bg-indigo-600 text-white px-6 py-2 rounded font-medium hover:bg-indigo-700"
          onClick={() => void handleExport()}
        >
          ייצוא
        </button>
      </section>
    </Layout>
  );
}
```

(Actual auth header retrieval should match however the rest of the app's `fetch`/API-wrapper layer attaches the JWT — check `frontend/src/api/client.ts` or equivalent for the existing convention and use that instead of a raw `localStorage.getItem("token")` if a shared wrapper already exists.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/planning/ExportPage.test.tsx`
Expected: PASS

- [ ] **Step 6: Run the full frontend suite, lint, and typecheck**

Run: `cd frontend && npm test && npm run lint && npm run typecheck`
Expected: PASS

- [ ] **Step 7: Manual verification in the running app**

Start the dev stack (`./dev.ps1` from repo root), navigate to `/planning/export`, check a mix of checkboxes (e.g. transparency + duty_types), click "ייצוא", and confirm a single `export.xlsx` downloads containing exactly the checked sheets with real data.

- [ ] **Step 8: Commit**

```bash
cd frontend && git add src/components/ExcelExportButton.tsx src/pages/planning/ExportPage.tsx src/pages/planning/ExportPage.test.tsx
git commit -m "feat: unify export page into one checkbox panel producing a single merged workbook"
```

---

## Task 18: End-to-end round-trip test

**Files:**
- Test: `backend/tests/integration/test_config_export_import_roundtrip.py` (new)

**Interfaces:**
- No new production code — this is a pure regression/integration test validating that Tasks 1–13 compose correctly: export current state, re-upload the exported file as a new session, confirm every row resolves as `update` (idempotent).

- [ ] **Step 1: Write the test**

```python
# backend/tests/integration/test_config_export_import_roundtrip.py
from __future__ import annotations

import uuid
from decimal import Decimal

from app.db.models import DutyLocation
from app.services.duty_config import create_duty_type, create_exemption_type, set_exemption_duty_types
from app.services.hierarchy import create_node, set_commander
from tests.helpers import auth_headers, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _token(soldier) -> str:
    return auth_headers(soldier)["Authorization"].split(" ", 1)[1]


def test_export_then_reimport_resolves_everything_as_update(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    commander = create_soldier(admin_session, personal_number=f"cmd_{_uid()}")
    node = create_node(admin_session, level="group", name=f"מדור_{_uid()}")
    set_commander(admin_session, node_id=node.id, commander_id=commander.id, actor_id=admin.id)
    loc = DutyLocation(name=f"שער_{_uid()}", base="בסיס א")
    admin_session.add(loc)
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    et = create_exemption_type(admin_session, name=f"et_{_uid()}")
    set_exemption_duty_types(admin_session, exemption_type_id=et.id, duty_type_ids=[dt.id])
    admin_session.commit()

    export_resp = client.get(
        "/api/config/export", headers={"Authorization": f"Bearer {_token(admin)}"}
    )
    assert export_resp.status_code == 200

    upload_resp = client.post(
        "/api/import/sessions?parser_id=v1_standard",
        files={"file": ("export.xlsx", export_resp.content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    assert upload_resp.status_code == 200
    preview = upload_resp.json()["preview"]

    for group in ("duty_locations", "hierarchy", "duty_types", "exemption_types"):
        for row in preview[group]:
            assert row["action"] == "update", f"{group} row {row['row']} expected update, got {row['action']}: {row['errors']}"
```

- [ ] **Step 2: Run the test**

Run: `cd backend && pytest tests/integration/test_config_export_import_roundtrip.py -v`
Expected: PASS if Tasks 1–13 are correctly composed. If it fails, the failure message names the group/row/error — fix the relevant resolver or export writer (most likely culprits: a name/format mismatch between the export column format in `config_export.py` and what the parser in `v1_standard.py` expects for that column, e.g. `active` boolean serialization or the `duty_managers`/`eligible_units` cell format).

- [ ] **Step 3: Run the entire backend suite one final time**

Run: `cd backend && pytest -q`
Expected: PASS, no regressions anywhere in the suite.

- [ ] **Step 4: Commit**

```bash
cd backend && git add tests/integration/test_config_export_import_roundtrip.py
git commit -m "test: add end-to-end export/re-import round-trip test for config sheets"
```

---

## Self-Review Notes

- **Spec coverage:** §1 Schema → Task 1. §2 Parser → Tasks 2–4. §3 Resolution → Tasks 5–8. §4 Review UI → Tasks 15–16. §5 Commit → Tasks 9–11. §6 Export → Task 12. §7 Frontend export UI → Task 17. §8 Template → Task 13. §9 Testing → covered throughout each task plus Task 18's round-trip test.
- **Type consistency:** `_resolve_duty_locations`/`_resolve_hierarchy`/`_resolve_duty_types`/`_resolve_exemption_types` dict keys (Tasks 5–8) are consumed verbatim by `confirm_session()` (Tasks 9–10) and by `config_export.py`'s column order (Task 12) — verified consistent field names (`resolved_eligible_node_ids`, `resolved_duty_type_ids`, `resolved_commander_id`, `duty_manager_refs`) across all three.
- **Deferred scope (explicitly, not a gap):** the combobox "pick a match" affordance for unresolved `parent_name`/`eligible_units`/`applies_to` names (Task 16, Step 3 note) — a row with an unresolved cross-reference name still surfaces as a clear row-level error today; adding the picker is a follow-up UI polish, not required for correctness.
