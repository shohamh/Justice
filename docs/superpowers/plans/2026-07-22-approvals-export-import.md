# Approvals Export/Import Implementation Plan (Part B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Full export/import round trip for exemption requests, personal-constraint requests, profile-edit (field-update) requests, enrollment requests, swap requests, and standalone granted exemptions — reusing the existing session-based import pipeline (`ImportSession`/`import_sessions.py`) and the `config_export.py`-style backend xlsx export pattern, with real xlsx-based end-to-end tests proving the round trip is lossless.

**Architecture:** Six new sheet types join the existing 8 (`soldiers`, `duty_shifts`, `shift_templates`, `assignments`, `duty_locations`, `hierarchy`, `duty_types`, `exemption_types`) in the same `ParsedImportData`/parser-registry/`ImportSession` machinery. Because these 6 resolvers are logically distinct from the existing config/data-sheet resolvers (approval workflows, not config or roster data) and `import_sessions.py` is already large, their resolvers live in a new sibling file, `backend/app/services/import_approvals.py`, imported into `_resolve_and_score`. Export is a new route file, `backend/app/routes/approvals_export.py`, mirroring `config_export.py`'s exact `_WRITERS`/`ALL_SHEETS`/`sheets`-param/`StreamingResponse` shape. This plan depends on Part A (`2026-07-22-live-computed-approval-scope.md`) having landed — the `swap_requests` sheet's `approval_log` column and its import-side restoration are built directly against Part A's lazy decision-log `SwapManagerApproval` model (`rejected`/`rejected_by`/`rejected_at` columns, no pre-populated roster).

**Tech Stack:** FastAPI/SQLAlchemy backend, openpyxl, React/TypeScript frontend, pytest.

## Global Constraints

- Every sheet's columns are human-readable (personal_number/full_name/type-name), never raw UUIDs, matching `config_export.py`'s existing convention — except `id`, included on every sheet (these entities have no natural business key) so import can match-and-update existing rows.
- Import reuses the **existing** `ImportSession` upload→draft→confirm pipeline — no new upload/review/confirm mechanism.
- Restoring an "update" row (an id that resolves to an existing record) writes `status`/`decided_by`/`decision_note`/etc. directly — this is an explicit data-restore operation, not a re-play of the normal single-step `approve_*`/`reject_*` service calls.
- Restoring a swap's `approval_log` column re-creates the exact decision-log rows it lists (one insert per segment) — it does not re-derive requirements from the current live hierarchy, since restoring history must reproduce recorded facts, not recompute them.
- `require_duty_manager_or_admin` gates the export endpoint, matching `config_export.py`.

---

### Task 1: Import schema — 6 new row types

**Files:**
- Modify: `backend/app/services/import_parsers/schema.py`

**Interfaces:**
- Produces: `ImportSwapRequestRow`, `ImportExemptionRequestRow`, `ImportSoldierFieldUpdateRow`, `ImportSoldierEnrollmentRequestRow`, `ImportPersonalConstraintRow`, `ImportSoldierExemptionRow` (all Pydantic `BaseModel`s with `source_row: int`) — consumed by Task 2 (parser) and Task 3 (resolvers).

- [ ] **Step 1: Add the 6 row schemas**

Append to `backend/app/services/import_parsers/schema.py`:

```python
class ImportSwapRequestRow(BaseModel):
    source_row: int
    id: str | None = None
    requesting_personal_number: str
    target_personal_number: str | None = None
    covering_personal_number: str | None = None
    duty_date: str
    status: str
    reason: str | None = None
    requester_side_approved: bool | None = None
    covering_side_approved: bool | None = None
    rejected_by_personal_number: str | None = None
    decision_note: str | None = None
    approval_log: str | None = None  # "side:kind:person_pn:approved|rejected:iso_datetime;..."


class ImportExemptionRequestRow(BaseModel):
    source_row: int
    id: str | None = None
    soldier_personal_number: str
    exemption_type_name: str
    start_date: str
    end_date: str | None = None
    reason: str | None = None
    status: str
    commander_approved_by_personal_number: str | None = None
    decided_by_personal_number: str | None = None
    decision_note: str | None = None
    files: str | None = None  # flattened filenames, comma-separated


class ImportSoldierFieldUpdateRow(BaseModel):
    source_row: int
    id: str | None = None
    soldier_personal_number: str
    field_name: str
    new_value: str
    previous_value: str | None = None
    status: str
    decided_by_personal_number: str | None = None
    decision_note: str | None = None


class ImportSoldierEnrollmentRequestRow(BaseModel):
    source_row: int
    id: str | None = None
    soldier_personal_number: str
    requested_node_name: str
    status: str
    decided_by_personal_number: str | None = None
    decision_note: str | None = None


class ImportPersonalConstraintRow(BaseModel):
    source_row: int
    id: str | None = None
    soldier_personal_number: str
    start_date: str
    end_date: str
    reason: str
    status: str
    decided_by_personal_number: str | None = None
    decision_note: str | None = None


class ImportSoldierExemptionRow(BaseModel):
    source_row: int
    id: str | None = None
    soldier_personal_number: str
    exemption_type_name: str
    start_date: str
    end_date: str | None = None
    reason: str | None = None
    granted_by_personal_number: str | None = None
    revoked: bool = False
    revoke_reason: str | None = None
```

- [ ] **Step 2: Add the 6 new fields to `ParsedImportData`**

In the same file, extend `ParsedImportData` (find its definition, ~line 114 per earlier exploration) with:

```python
    swap_requests: list[ImportSwapRequestRow] = []
    exemption_requests: list[ImportExemptionRequestRow] = []
    soldier_field_updates: list[ImportSoldierFieldUpdateRow] = []
    soldier_enrollment_requests: list[ImportSoldierEnrollmentRequestRow] = []
    personal_constraints: list[ImportPersonalConstraintRow] = []
    soldier_exemptions: list[ImportSoldierExemptionRow] = []
```

- [ ] **Step 3: Type-check the schema module compiles**

Run: `python -c "import app.services.import_parsers.schema"` (from `backend/`, venv active)
Expected: no import errors.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/import_parsers/schema.py
git commit -m "feat: add import row schemas for the 6 approvals/exemptions sheets"
```

---

### Task 2: Parser — read the 6 new sheets

**Files:**
- Modify: `backend/app/services/import_parsers/v1_standard.py`

**Interfaces:**
- Consumes: the 6 schemas (Task 1), `_sheet_rows`/`_parse_bool`/`_parse_date` helpers (already exist in this file)
- Produces: `V1StandardParser.parse()` populates the 6 new `ParsedImportData` fields — consumed by Task 3

- [ ] **Step 1: Add the 6 sheet names to `KNOWN_SHEETS`**

In `v1_standard.py`, extend `KNOWN_SHEETS` (line ~23-26):

```python
KNOWN_SHEETS = {
    "soldiers", "duty_shifts", "assignments", "duty_locations", "hierarchy",
    "duty_types", "exemption_types", "shift_templates",
    "swap_requests", "exemption_requests", "soldier_field_updates",
    "soldier_enrollment_requests", "personal_constraints", "soldier_exemptions",
}
```

- [ ] **Step 2: Add the 6 sheet-reading comprehensions inside `parse()`**

Add alongside the existing `soldiers = [...]`/`duty_shifts = [...]` comprehensions:

```python
        swap_requests = [
            ImportSwapRequestRow(
                source_row=r["_row"],
                id=str(r.get("id") or "").strip() or None,
                requesting_personal_number=str(r.get("requesting_personal_number") or "").strip(),
                target_personal_number=str(r.get("target_personal_number") or "").strip() or None,
                covering_personal_number=str(r.get("covering_personal_number") or "").strip() or None,
                duty_date=_parse_date(r.get("duty_date")) or "",
                status=str(r.get("status") or "").strip(),
                reason=str(r.get("reason") or "").strip() or None,
                requester_side_approved=_parse_bool(r.get("requester_side_approved")),
                covering_side_approved=_parse_bool(r.get("covering_side_approved")),
                rejected_by_personal_number=str(r.get("rejected_by_personal_number") or "").strip() or None,
                decision_note=str(r.get("decision_note") or "").strip() or None,
                approval_log=str(r.get("approval_log") or "").strip() or None,
            )
            for r in _sheet_rows(wb, "swap_requests")
        ]

        exemption_requests = [
            ImportExemptionRequestRow(
                source_row=r["_row"],
                id=str(r.get("id") or "").strip() or None,
                soldier_personal_number=str(r.get("soldier_personal_number") or "").strip(),
                exemption_type_name=str(r.get("exemption_type_name") or "").strip(),
                start_date=_parse_date(r.get("start_date")) or "",
                end_date=_parse_date(r.get("end_date")),
                reason=str(r.get("reason") or "").strip() or None,
                status=str(r.get("status") or "").strip(),
                commander_approved_by_personal_number=str(r.get("commander_approved_by_personal_number") or "").strip() or None,
                decided_by_personal_number=str(r.get("decided_by_personal_number") or "").strip() or None,
                decision_note=str(r.get("decision_note") or "").strip() or None,
                files=str(r.get("files") or "").strip() or None,
            )
            for r in _sheet_rows(wb, "exemption_requests")
        ]

        soldier_field_updates = [
            ImportSoldierFieldUpdateRow(
                source_row=r["_row"],
                id=str(r.get("id") or "").strip() or None,
                soldier_personal_number=str(r.get("soldier_personal_number") or "").strip(),
                field_name=str(r.get("field_name") or "").strip(),
                new_value=str(r.get("new_value") or "").strip(),
                previous_value=str(r.get("previous_value") or "").strip() or None,
                status=str(r.get("status") or "").strip(),
                decided_by_personal_number=str(r.get("decided_by_personal_number") or "").strip() or None,
                decision_note=str(r.get("decision_note") or "").strip() or None,
            )
            for r in _sheet_rows(wb, "soldier_field_updates")
        ]

        soldier_enrollment_requests = [
            ImportSoldierEnrollmentRequestRow(
                source_row=r["_row"],
                id=str(r.get("id") or "").strip() or None,
                soldier_personal_number=str(r.get("soldier_personal_number") or "").strip(),
                requested_node_name=str(r.get("requested_node_name") or "").strip(),
                status=str(r.get("status") or "").strip(),
                decided_by_personal_number=str(r.get("decided_by_personal_number") or "").strip() or None,
                decision_note=str(r.get("decision_note") or "").strip() or None,
            )
            for r in _sheet_rows(wb, "soldier_enrollment_requests")
        ]

        personal_constraints = [
            ImportPersonalConstraintRow(
                source_row=r["_row"],
                id=str(r.get("id") or "").strip() or None,
                soldier_personal_number=str(r.get("soldier_personal_number") or "").strip(),
                start_date=_parse_date(r.get("start_date")) or "",
                end_date=_parse_date(r.get("end_date")) or "",
                reason=str(r.get("reason") or "").strip(),
                status=str(r.get("status") or "").strip(),
                decided_by_personal_number=str(r.get("decided_by_personal_number") or "").strip() or None,
                decision_note=str(r.get("decision_note") or "").strip() or None,
            )
            for r in _sheet_rows(wb, "personal_constraints")
        ]

        soldier_exemptions = [
            ImportSoldierExemptionRow(
                source_row=r["_row"],
                id=str(r.get("id") or "").strip() or None,
                soldier_personal_number=str(r.get("soldier_personal_number") or "").strip(),
                exemption_type_name=str(r.get("exemption_type_name") or "").strip(),
                start_date=_parse_date(r.get("start_date")) or "",
                end_date=_parse_date(r.get("end_date")),
                reason=str(r.get("reason") or "").strip() or None,
                granted_by_personal_number=str(r.get("granted_by_personal_number") or "").strip() or None,
                revoked=bool(_parse_bool(r.get("revoked"))),
                revoke_reason=str(r.get("revoke_reason") or "").strip() or None,
            )
            for r in _sheet_rows(wb, "soldier_exemptions")
        ]
```

Add the 6 new imports to the file's existing `from app.services.import_parsers.schema import (...)` block, and pass all 6 new lists into the final `ParsedImportData(...)` constructor call at the end of `parse()`.

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/import_parsers/v1_standard.py
git commit -m "feat: parse the 6 approvals/exemptions sheets in the v1_standard importer"
```

(No isolated test for this task alone — Task 3's resolver tests exercise the parser transitively, matching this codebase's existing convention where `test_import_sessions_service.py` tests resolvers via `create_session(...)`, not the parser in isolation.)

---

### Task 3: Resolvers — `backend/app/services/import_approvals.py` (new file)

**Files:**
- Create: `backend/app/services/import_approvals.py`
- Modify: `backend/app/services/import_sessions.py` (`_resolve_and_score`, `confirm_session`)
- Test: `backend/app/services/tests/test_import_approvals_service.py` (new)

**Interfaces:**
- Consumes: `ParsedImportData` fields from Task 1/2
- Produces: `resolve_swap_requests`, `resolve_exemption_requests`, `resolve_soldier_field_updates`, `resolve_soldier_enrollment_requests`, `resolve_personal_constraints`, `resolve_soldier_exemptions` (each `(session, data, overrides=None) -> list[dict]`) — consumed by `_resolve_and_score` and Task 4 (confirm)

- [ ] **Step 1: Write the failing tests**

```python
# backend/app/services/tests/test_import_approvals_service.py
from __future__ import annotations

import io
import uuid
from datetime import date as date_type

import openpyxl
import pytest

from app.db.models import ExemptionType, PersonalConstraint, Soldier
import app.services.import_parsers.v1_standard  # noqa: F401
from app.services.import_sessions import confirm_session, create_session, set_selections, reparse_session
from tests.helpers import create_node, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _to_bytes(wb) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _wb_with_personal_constraints(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("personal_constraints")
    ws.append([
        "id", "soldier_personal_number", "start_date", "end_date", "reason",
        "status", "decided_by_personal_number", "decision_note",
    ])
    for r in rows:
        ws.append(r)
    return wb


def test_personal_constraint_new_row_resolves(admin_session):
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    admin_session.commit()

    wb = _wb_with_personal_constraints([
        ["", soldier.personal_number, "15.06.2024", "16.06.2024", "reason", "pending", "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    row = sess.parsed_state["personal_constraints"][0]
    assert row["action"] == "new"
    assert row["resolved_soldier_id"] == str(soldier.id)


def test_personal_constraint_existing_id_resolves_to_update(admin_session):
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    existing = PersonalConstraint(
        soldier_id=soldier.id, start_date=date_type(2024, 1, 1), end_date=date_type(2024, 1, 2),
        reason="old", status="pending",
    )
    admin_session.add(existing)
    admin_session.commit()

    wb = _wb_with_personal_constraints([
        [str(existing.id), soldier.personal_number, "15.06.2024", "16.06.2024", "new reason", "approved", f"adm_{_uid()}", "ok"],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm2_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    row = sess.parsed_state["personal_constraints"][0]
    assert row["action"] == "update"
    assert row["existing_id"] == str(existing.id)


def test_personal_constraint_confirm_restores_decided_status(admin_session):
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}")
    admin_session.commit()

    wb = _wb_with_personal_constraints([
        ["", soldier.personal_number, "15.06.2024", "16.06.2024", "reason", "approved", decider.personal_number, "note"],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    created = admin_session.execute(
        select(PersonalConstraint).where(PersonalConstraint.soldier_id == soldier.id)
    ).scalar_one()
    assert created.status == "approved"
    assert created.decided_by == decider.id
    assert created.decision_note == "note"
```

(Write parallel tests for the other 5 sheet types following this exact structure — one `new` resolution test, one `id`-matches-existing→`update` test, one confirm-persists-full-status test per type. For `swap_requests` specifically, add a test that seeds an `approval_log` value and asserts `confirm_session` creates the corresponding `SwapManagerApproval` decision-log rows with the right `side`/`approver_kind`/`approved`/`rejected` values — this is the one genuinely novel restoration path, since it's reconstructing decision-log rows rather than a single status field.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest app/services/tests/test_import_approvals_service.py -v`
Expected: FAIL — `app.services.import_approvals` doesn't exist, `ParsedImportData` has no `personal_constraints` field consumed yet.

- [ ] **Step 3: Write the resolvers**

```python
# backend/app/services/import_approvals.py
from __future__ import annotations

import uuid
from datetime import date as date_type

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    ExemptionRequest, ExemptionType, HierarchyNode, PersonalConstraint,
    Soldier, SoldierEnrollmentRequest, SoldierExemption, SoldierFieldUpdate,
    SwapRequest,
)
from app.services.import_parsers.schema import ParsedImportData


def _soldiers_by_pn(session: Session) -> dict[str, Soldier]:
    return {s.personal_number: s for s in session.execute(select(Soldier)).scalars()}


def resolve_personal_constraints(session: Session, data: ParsedImportData, overrides: dict[str, dict] | None = None) -> list[dict]:
    overrides = overrides or {}
    soldiers_by_pn = _soldiers_by_pn(session)
    out = []
    for row in data.personal_constraints:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        soldier_pn = field("soldier_personal_number", row.soldier_personal_number)
        start_date = field("start_date", row.start_date)
        end_date = field("end_date", row.end_date)
        reason = field("reason", row.reason)
        status = field("status", row.status)
        decided_by_pn = field("decided_by_personal_number", row.decided_by_personal_number)
        decision_note = field("decision_note", row.decision_note)

        soldier = soldiers_by_pn.get(soldier_pn) if soldier_pn else None
        if soldier is None:
            errors.append(f"חייל לא מזוהה '{soldier_pn}'")
        decided_by = soldiers_by_pn.get(decided_by_pn) if decided_by_pn else None
        if decided_by_pn and decided_by is None:
            errors.append(f"מחליט לא מזוהה '{decided_by_pn}'")
        if status not in ("pending", "approved", "rejected"):
            errors.append(f"סטטוס לא תקין '{status}'")

        existing = None
        if row.id:
            try:
                existing = session.get(PersonalConstraint, uuid.UUID(row.id))
            except ValueError:
                errors.append(f"מזהה לא תקין '{row.id}'")

        action = "error" if errors else ("update" if existing is not None else "new")
        out.append({
            "row": row.source_row, "action": action, "errors": errors,
            "id": row.id, "soldier_personal_number": soldier_pn,
            "resolved_soldier_id": str(soldier.id) if soldier else None,
            "start_date": start_date, "end_date": end_date, "reason": reason, "status": status,
            "decided_by_personal_number": decided_by_pn,
            "resolved_decided_by_id": str(decided_by.id) if decided_by else None,
            "decision_note": decision_note,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def resolve_soldier_field_updates(session: Session, data: ParsedImportData, overrides: dict[str, dict] | None = None) -> list[dict]:
    overrides = overrides or {}
    soldiers_by_pn = _soldiers_by_pn(session)
    out = []
    for row in data.soldier_field_updates:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        soldier_pn = field("soldier_personal_number", row.soldier_personal_number)
        field_name = field("field_name", row.field_name)
        new_value = field("new_value", row.new_value)
        previous_value = field("previous_value", row.previous_value)
        status = field("status", row.status)
        decided_by_pn = field("decided_by_personal_number", row.decided_by_personal_number)
        decision_note = field("decision_note", row.decision_note)

        soldier = soldiers_by_pn.get(soldier_pn) if soldier_pn else None
        if soldier is None:
            errors.append(f"חייל לא מזוהה '{soldier_pn}'")
        decided_by = soldiers_by_pn.get(decided_by_pn) if decided_by_pn else None
        if decided_by_pn and decided_by is None:
            errors.append(f"מחליט לא מזוהה '{decided_by_pn}'")
        if not field_name:
            errors.append("חסר שם שדה")
        if status not in ("pending", "approved", "rejected"):
            errors.append(f"סטטוס לא תקין '{status}'")

        existing = None
        if row.id:
            try:
                existing = session.get(SoldierFieldUpdate, uuid.UUID(row.id))
            except ValueError:
                errors.append(f"מזהה לא תקין '{row.id}'")

        action = "error" if errors else ("update" if existing is not None else "new")
        out.append({
            "row": row.source_row, "action": action, "errors": errors,
            "id": row.id, "soldier_personal_number": soldier_pn,
            "resolved_soldier_id": str(soldier.id) if soldier else None,
            "field_name": field_name, "new_value": new_value, "previous_value": previous_value,
            "status": status, "decided_by_personal_number": decided_by_pn,
            "resolved_decided_by_id": str(decided_by.id) if decided_by else None,
            "decision_note": decision_note,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def resolve_soldier_enrollment_requests(session: Session, data: ParsedImportData, overrides: dict[str, dict] | None = None) -> list[dict]:
    overrides = overrides or {}
    soldiers_by_pn = _soldiers_by_pn(session)
    nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}
    out = []
    for row in data.soldier_enrollment_requests:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        soldier_pn = field("soldier_personal_number", row.soldier_personal_number)
        requested_node_name = field("requested_node_name", row.requested_node_name)
        status = field("status", row.status)
        decided_by_pn = field("decided_by_personal_number", row.decided_by_personal_number)
        decision_note = field("decision_note", row.decision_note)

        soldier = soldiers_by_pn.get(soldier_pn) if soldier_pn else None
        if soldier is None:
            errors.append(f"חייל לא מזוהה '{soldier_pn}'")
        node = nodes_by_name.get(requested_node_name) if requested_node_name else None
        if node is None:
            errors.append(f"יחידה לא מזוהה '{requested_node_name}'")
        decided_by = soldiers_by_pn.get(decided_by_pn) if decided_by_pn else None
        if decided_by_pn and decided_by is None:
            errors.append(f"מחליט לא מזוהה '{decided_by_pn}'")
        if status not in ("pending", "commander_approved", "approved", "rejected"):
            errors.append(f"סטטוס לא תקין '{status}'")

        existing = None
        if row.id:
            try:
                existing = session.get(SoldierEnrollmentRequest, uuid.UUID(row.id))
            except ValueError:
                errors.append(f"מזהה לא תקין '{row.id}'")

        action = "error" if errors else ("update" if existing is not None else "new")
        out.append({
            "row": row.source_row, "action": action, "errors": errors,
            "id": row.id, "soldier_personal_number": soldier_pn,
            "resolved_soldier_id": str(soldier.id) if soldier else None,
            "requested_node_name": requested_node_name,
            "resolved_node_id": str(node.id) if node else None,
            "status": status, "decided_by_personal_number": decided_by_pn,
            "resolved_decided_by_id": str(decided_by.id) if decided_by else None,
            "decision_note": decision_note,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def resolve_soldier_exemptions(session: Session, data: ParsedImportData, overrides: dict[str, dict] | None = None) -> list[dict]:
    overrides = overrides or {}
    soldiers_by_pn = _soldiers_by_pn(session)
    exemption_types_by_name = {et.name: et for et in session.execute(select(ExemptionType)).scalars()}
    out = []
    for row in data.soldier_exemptions:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        soldier_pn = field("soldier_personal_number", row.soldier_personal_number)
        exemption_type_name = field("exemption_type_name", row.exemption_type_name)
        start_date = field("start_date", row.start_date)
        end_date = field("end_date", row.end_date)
        reason = field("reason", row.reason)
        granted_by_pn = field("granted_by_personal_number", row.granted_by_personal_number)
        revoked = field("revoked", row.revoked)
        revoke_reason = field("revoke_reason", row.revoke_reason)

        soldier = soldiers_by_pn.get(soldier_pn) if soldier_pn else None
        if soldier is None:
            errors.append(f"חייל לא מזוהה '{soldier_pn}'")
        exemption_type = exemption_types_by_name.get(exemption_type_name) if exemption_type_name else None
        if exemption_type is None:
            errors.append(f"סוג פטור לא מזוהה '{exemption_type_name}'")
        granted_by = soldiers_by_pn.get(granted_by_pn) if granted_by_pn else None
        if granted_by_pn and granted_by is None:
            errors.append(f"מעניק לא מזוהה '{granted_by_pn}'")

        existing = None
        if row.id:
            try:
                existing = session.get(SoldierExemption, uuid.UUID(row.id))
            except ValueError:
                errors.append(f"מזהה לא תקין '{row.id}'")

        action = "error" if errors else ("update" if existing is not None else "new")
        out.append({
            "row": row.source_row, "action": action, "errors": errors,
            "id": row.id, "soldier_personal_number": soldier_pn,
            "resolved_soldier_id": str(soldier.id) if soldier else None,
            "exemption_type_name": exemption_type_name,
            "resolved_exemption_type_id": str(exemption_type.id) if exemption_type else None,
            "start_date": start_date, "end_date": end_date, "reason": reason,
            "granted_by_personal_number": granted_by_pn,
            "resolved_granted_by_id": str(granted_by.id) if granted_by else None,
            "revoked": revoked, "revoke_reason": revoke_reason,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def resolve_exemption_requests(session: Session, data: ParsedImportData, overrides: dict[str, dict] | None = None) -> list[dict]:
    overrides = overrides or {}
    soldiers_by_pn = _soldiers_by_pn(session)
    exemption_types_by_name = {et.name: et for et in session.execute(select(ExemptionType)).scalars()}
    out = []
    for row in data.exemption_requests:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        soldier_pn = field("soldier_personal_number", row.soldier_personal_number)
        exemption_type_name = field("exemption_type_name", row.exemption_type_name)
        start_date = field("start_date", row.start_date)
        end_date = field("end_date", row.end_date)
        reason = field("reason", row.reason)
        status = field("status", row.status)
        commander_approved_by_pn = field("commander_approved_by_personal_number", row.commander_approved_by_personal_number)
        decided_by_pn = field("decided_by_personal_number", row.decided_by_personal_number)
        decision_note = field("decision_note", row.decision_note)
        files = field("files", row.files)

        soldier = soldiers_by_pn.get(soldier_pn) if soldier_pn else None
        if soldier is None:
            errors.append(f"חייל לא מזוהה '{soldier_pn}'")
        exemption_type = exemption_types_by_name.get(exemption_type_name) if exemption_type_name else None
        if exemption_type is None:
            errors.append(f"סוג פטור לא מזוהה '{exemption_type_name}'")
        commander_approved_by = soldiers_by_pn.get(commander_approved_by_pn) if commander_approved_by_pn else None
        if commander_approved_by_pn and commander_approved_by is None:
            errors.append(f"מפקד מאשר לא מזוהה '{commander_approved_by_pn}'")
        decided_by = soldiers_by_pn.get(decided_by_pn) if decided_by_pn else None
        if decided_by_pn and decided_by is None:
            errors.append(f"מחליט לא מזוהה '{decided_by_pn}'")
        if status not in ("pending_commander", "pending_duty_manager", "approved", "rejected"):
            errors.append(f"סטטוס לא תקין '{status}'")

        existing = None
        if row.id:
            try:
                existing = session.get(ExemptionRequest, uuid.UUID(row.id))
            except ValueError:
                errors.append(f"מזהה לא תקין '{row.id}'")

        action = "error" if errors else ("update" if existing is not None else "new")
        out.append({
            "row": row.source_row, "action": action, "errors": errors,
            "id": row.id, "soldier_personal_number": soldier_pn,
            "resolved_soldier_id": str(soldier.id) if soldier else None,
            "exemption_type_name": exemption_type_name,
            "resolved_exemption_type_id": str(exemption_type.id) if exemption_type else None,
            "start_date": start_date, "end_date": end_date, "reason": reason, "status": status,
            "commander_approved_by_personal_number": commander_approved_by_pn,
            "resolved_commander_approved_by_id": str(commander_approved_by.id) if commander_approved_by else None,
            "decided_by_personal_number": decided_by_pn,
            "resolved_decided_by_id": str(decided_by.id) if decided_by else None,
            "decision_note": decision_note, "files": files,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def _parse_approval_log(raw: str | None) -> list[dict]:
    """Parse 'side:kind:person_pn:approved|rejected:iso_datetime;...' into
    dicts. Malformed segments are skipped individually (mirrors
    _parse_node_quotas' per-segment tolerance in v1_standard.py) rather than
    failing the whole row."""
    if not raw:
        return []
    out = []
    for segment in raw.split(";"):
        segment = segment.strip()
        if not segment:
            continue
        parts = segment.split(":")
        if len(parts) != 5:
            continue
        side, kind, person_pn, outcome, at = parts
        if side not in ("requester", "covering") or kind not in ("commander", "duty_manager") or outcome not in ("approved", "rejected"):
            continue
        out.append({"side": side, "kind": kind, "person_pn": person_pn, "outcome": outcome, "at": at})
    return out


def resolve_swap_requests(session: Session, data: ParsedImportData, overrides: dict[str, dict] | None = None) -> list[dict]:
    overrides = overrides or {}
    soldiers_by_pn = _soldiers_by_pn(session)
    out = []
    for row in data.swap_requests:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        requesting_pn = field("requesting_personal_number", row.requesting_personal_number)
        target_pn = field("target_personal_number", row.target_personal_number)
        covering_pn = field("covering_personal_number", row.covering_personal_number)
        duty_date = field("duty_date", row.duty_date)
        status = field("status", row.status)
        reason = field("reason", row.reason)
        requester_side_approved = field("requester_side_approved", row.requester_side_approved)
        covering_side_approved = field("covering_side_approved", row.covering_side_approved)
        rejected_by_pn = field("rejected_by_personal_number", row.rejected_by_personal_number)
        decision_note = field("decision_note", row.decision_note)
        approval_log_raw = field("approval_log", row.approval_log)

        requesting = soldiers_by_pn.get(requesting_pn) if requesting_pn else None
        if requesting is None:
            errors.append(f"מבקש לא מזוהה '{requesting_pn}'")
        target = soldiers_by_pn.get(target_pn) if target_pn else None
        if target_pn and target is None:
            errors.append(f"חייל יעד לא מזוהה '{target_pn}'")
        covering = soldiers_by_pn.get(covering_pn) if covering_pn else None
        if covering_pn and covering is None:
            errors.append(f"מכסה לא מזוהה '{covering_pn}'")
        rejected_by = soldiers_by_pn.get(rejected_by_pn) if rejected_by_pn else None
        if rejected_by_pn and rejected_by is None:
            errors.append(f"דוחה לא מזוהה '{rejected_by_pn}'")
        if status not in ("open", "pending_approval", "applied", "rejected", "cancelled"):
            errors.append(f"סטטוס לא תקין '{status}'")

        approval_log_parsed = _parse_approval_log(approval_log_raw)
        resolved_log = []
        for entry in approval_log_parsed:
            person = soldiers_by_pn.get(entry["person_pn"])
            if person is None:
                errors.append(f"מאשר/דוחה לא מזוהה בלוג האישורים '{entry['person_pn']}'")
                continue
            resolved_log.append({**entry, "resolved_person_id": str(person.id)})

        existing = None
        if not row.id:
            errors.append("ייבוא בקשות החלפה נתמך רק לעדכון — נדרש מזהה (id)")
        else:
            try:
                existing = session.get(SwapRequest, uuid.UUID(row.id))
                if existing is None:
                    errors.append(f"בקשת החלפה לא נמצאה עבור מזהה '{row.id}'")
            except ValueError:
                errors.append(f"מזהה לא תקין '{row.id}'")

        # Swap-request import is update-only by design: SwapRequest.duty_assignment_id
        # is a required FK with no natural round-trip column on this sheet (no stable
        # business key like duty_type_name+duty_location_name+date exists for an
        # arbitrary historical assignment), so creating a brand-new swap request via
        # spreadsheet is out of scope — only restoring/updating an existing one's
        # decided/rejected state and approval_log is supported.
        action = "error" if errors else "update"
        out.append({
            "row": row.source_row, "action": action, "errors": errors,
            "id": row.id,
            "requesting_personal_number": requesting_pn,
            "resolved_requesting_soldier_id": str(requesting.id) if requesting else None,
            "target_personal_number": target_pn,
            "resolved_target_soldier_id": str(target.id) if target else None,
            "covering_personal_number": covering_pn,
            "resolved_covering_soldier_id": str(covering.id) if covering else None,
            "duty_date": duty_date, "status": status, "reason": reason,
            "requester_side_approved": requester_side_approved,
            "covering_side_approved": covering_side_approved,
            "rejected_by_personal_number": rejected_by_pn,
            "resolved_rejected_by_id": str(rejected_by.id) if rejected_by else None,
            "decision_note": decision_note,
            "approval_log": resolved_log,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out
```

- [ ] **Step 4: Wire into `_resolve_and_score`**

In `backend/app/services/import_sessions.py`, import the 6 new resolvers at the top:

```python
from app.services.import_approvals import (
    resolve_exemption_requests, resolve_personal_constraints, resolve_soldier_enrollment_requests,
    resolve_soldier_exemptions, resolve_soldier_field_updates, resolve_swap_requests,
)
```

Add 6 new dict entries to `_resolve_and_score`'s return value, each following the existing `fo.get("<group>", {})` pattern:

```python
        "personal_constraints": resolve_personal_constraints(session, data, fo.get("personal_constraints", {})),
        "soldier_field_updates": resolve_soldier_field_updates(session, data, fo.get("soldier_field_updates", {})),
        "soldier_enrollment_requests": resolve_soldier_enrollment_requests(session, data, fo.get("soldier_enrollment_requests", {})),
        "soldier_exemptions": resolve_soldier_exemptions(session, data, fo.get("soldier_exemptions", {})),
        "exemption_requests": resolve_exemption_requests(session, data, fo.get("exemption_requests", {})),
        "swap_requests": resolve_swap_requests(session, data, fo.get("swap_requests", {})),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest app/services/tests/test_import_approvals_service.py -v`
Expected: PASS

- [ ] **Step 6: Run the full backend suite for regressions**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/import_approvals.py backend/app/services/import_sessions.py backend/app/services/tests/test_import_approvals_service.py
git commit -m "feat: add resolvers for the 6 approvals/exemptions import sheets"
```

---

### Task 4: `confirm_session` — create/update the 6 new record types

**Files:**
- Modify: `backend/app/services/import_sessions.py` (`confirm_session`)
- Test: `backend/app/services/tests/test_import_approvals_service.py`

**Interfaces:**
- Consumes: the 6 resolved row-dict shapes from Task 3
- Produces: `confirm_session` creates/updates `PersonalConstraint`, `SoldierFieldUpdate`, `SoldierEnrollmentRequest`, `SoldierExemption`, `ExemptionRequest`, `SwapRequest`+`SwapManagerApproval` rows

- [ ] **Step 1: Write the failing tests** (already included in Task 3's Step 1 — `test_personal_constraint_confirm_restores_decided_status` and its 5 siblings for the other types; if not all written in Task 3, complete them now, especially the `swap_requests`/`approval_log` restoration test described in Task 3 Step 1's closing note.)

- [ ] **Step 2: Add 6 new blocks to `confirm_session`, following the exact `_effective_action`/`skip`/`begin_nested` pattern already used for every existing group**

For each of the 5 single-status types, the pattern is identical (shown here for `personal_constraints`; replicate for `soldier_field_updates`, `soldier_enrollment_requests`, `soldier_exemptions`, `exemption_requests` with their respective model/field names from Task 3's resolver output):

```python
    # ── Personal constraints ────────────────────────────────────────────
    for row in state.get("personal_constraints", []):
        effective = _effective_action(selections, "personal_constraints", row)
        if row["action"] == "error" or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                if effective == "new":
                    pc = PersonalConstraint(
                        soldier_id=uuid.UUID(row["resolved_soldier_id"]),
                        start_date=date_type.fromisoformat(row["start_date"]),
                        end_date=date_type.fromisoformat(row["end_date"]),
                        reason=row["reason"],
                        status=row["status"],
                    )
                    if row.get("resolved_decided_by_id"):
                        pc.decided_by = uuid.UUID(row["resolved_decided_by_id"])
                        pc.decided_at = datetime.now(UTC)
                    pc.decision_note = row.get("decision_note")
                    session.add(pc)
                    created += 1
                elif effective == "update" and row.get("existing_id"):
                    pc = session.get(PersonalConstraint, uuid.UUID(row["existing_id"]))
                    if pc is not None:
                        pc.start_date = date_type.fromisoformat(row["start_date"])
                        pc.end_date = date_type.fromisoformat(row["end_date"])
                        pc.reason = row["reason"]
                        pc.status = row["status"]
                        if row.get("resolved_decided_by_id"):
                            pc.decided_by = uuid.UUID(row["resolved_decided_by_id"])
                        pc.decision_note = row.get("decision_note")
                        updated += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "personal_constraints", "error": str(exc)})
```

`soldier_exemptions` additionally handles `revoked`/`revoke_reason` (setting `revoked_at`/`revoke_reason` when `row["revoked"]` is true, mirroring the model's `revoked_at`/`revoked_by`/`revoke_reason` columns).

`exemption_requests` additionally sets `commander_approved_by` from `resolved_commander_approved_by_id` when present, alongside `decided_by`.

For `swap_requests`, the block is more involved because of the decision-log restoration:

```python
    # ── Swap requests ───────────────────────────────────────────────────
    for row in state.get("swap_requests", []):
        effective = _effective_action(selections, "swap_requests", row)
        if row["action"] == "error" or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                # update-only (see resolve_swap_requests in Task 3) — action is
                # always "update" for a non-error, non-skipped row; "existing_id"
                # is always present since resolution requires it.
                if effective != "update" or not row.get("existing_id"):
                    skipped += 1
                    continue
                swap = session.get(SwapRequest, uuid.UUID(row["existing_id"]))
                if swap is None:
                    skipped += 1
                    continue
                swap.status = row["status"]
                swap.reason = row.get("reason")
                swap.requester_side_approved = row.get("requester_side_approved")
                swap.covering_side_approved = row.get("covering_side_approved")
                swap.decision_note = row.get("decision_note")
                if row.get("resolved_rejected_by_id"):
                    swap.rejected_by = uuid.UUID(row["resolved_rejected_by_id"])
                if row.get("resolved_covering_soldier_id"):
                    swap.covering_soldier_id = uuid.UUID(row["resolved_covering_soldier_id"])
                updated += 1

                # Restore the approval_log's decision-log rows — one insert
                # per segment, exactly as recorded (not re-derived from the
                # live hierarchy), skipping any (side, kind, person) already
                # present for this swap (idempotent re-confirm).
                for entry in row.get("approval_log", []):
                    existing_decision = session.execute(
                        select(SwapManagerApproval).where(
                            SwapManagerApproval.swap_request_id == swap.id,
                            SwapManagerApproval.side == entry["side"],
                            SwapManagerApproval.approver_kind == entry["kind"],
                            SwapManagerApproval.commander_id == uuid.UUID(entry["resolved_person_id"]),
                        )
                    ).scalar_one_or_none()
                    if existing_decision is None:
                        existing_decision = SwapManagerApproval(
                            swap_request_id=swap.id, side=entry["side"], approver_kind=entry["kind"],
                            commander_id=uuid.UUID(entry["resolved_person_id"]),
                        )
                        session.add(existing_decision)
                    at = datetime.fromisoformat(entry["at"]) if entry.get("at") else datetime.now(UTC)
                    if entry["outcome"] == "approved":
                        existing_decision.approved = True
                        existing_decision.approved_by = uuid.UUID(entry["resolved_person_id"])
                        existing_decision.approved_at = at
                    else:
                        existing_decision.rejected = True
                        existing_decision.rejected_by = uuid.UUID(entry["resolved_person_id"])
                        existing_decision.rejected_at = at
        except Exception as exc:
            errors.append({"row": row["row"], "type": "swap_requests", "error": str(exc)})
```

Swap-request import is deliberately update-only (see Task 3's `resolve_swap_requests`): `SwapRequest.duty_assignment_id` is a required FK with no stable round-trip column on this sheet, so creating a brand-new swap request via spreadsheet is out of scope — only restoring/updating an existing one's decided/rejected state and `approval_log` is supported.

- [ ] **Step 3: Run tests to verify they pass**

Run: `pytest app/services/tests/test_import_approvals_service.py -v`
Expected: PASS

- [ ] **Step 4: Run the full backend suite for regressions**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/import_sessions.py backend/app/services/tests/test_import_approvals_service.py
git commit -m "feat: create/update the 6 approvals/exemptions record types on import confirm"
```

---

### Task 5: Backend export route

**Files:**
- Create: `backend/app/routes/approvals_export.py`
- Modify: `backend/app/main.py` (or wherever routers are registered — find via `grep -n "include_router" backend/app/main.py`)
- Test: `backend/app/routes/tests/test_approvals_export.py` (new — find the correct test directory convention via `find backend -iname "test_config_export*"`, since `config_export.py`'s own test file is the closest sibling to model this on)

**Interfaces:**
- Produces: `GET /approvals/export?sheets=...` — consumed by Task 6 (frontend) and Task 7 (e2e tests)

- [ ] **Step 1: Write the failing test**

Model this directly on `config_export.py`'s own test file (read it first to match conventions exactly):

```python
def test_export_personal_constraints_sheet(client, admin_headers, ...):
    # seed a soldier + a decided PersonalConstraint, GET
    # /approvals/export?sheets=personal_constraints, parse the returned
    # xlsx bytes with openpyxl, assert the sheet exists with the right
    # header row and one data row matching the seeded values.
    ...
```

- [ ] **Step 2: Write the route, mirroring `config_export.py` exactly**

```python
# backend/app/routes/approvals_export.py
from __future__ import annotations

import io

import openpyxl
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_duty_manager_or_admin
from app.db.models import (
    ExemptionRequest, ExemptionRequestFile, ExemptionType, HierarchyNode,
    PersonalConstraint, Soldier, SoldierEnrollmentRequest, SoldierExemption,
    SoldierFieldUpdate, SwapManagerApproval, SwapRequest,
)
from app.db.session import get_session

router = APIRouter(prefix="/approvals", tags=["approvals-export"])

ALL_SHEETS = [
    "swap_requests", "exemption_requests", "soldier_field_updates",
    "soldier_enrollment_requests", "personal_constraints", "soldier_exemptions",
]


def _soldier_label(soldiers_by_id: dict, soldier_id) -> tuple[str, str]:
    s = soldiers_by_id.get(soldier_id)
    return (s.personal_number, s.full_name) if s else ("", "")


def _write_personal_constraints(wb: openpyxl.Workbook, session: Session) -> None:
    ws = wb.create_sheet("personal_constraints")
    ws.append([
        "id", "soldier_personal_number", "soldier_name", "start_date", "end_date",
        "reason", "status", "decided_by_personal_number", "decision_note", "created_at",
    ])
    soldiers_by_id = {s.id: s for s in session.execute(select(Soldier)).scalars()}
    for c in session.execute(select(PersonalConstraint)).scalars():
        pn, name = _soldier_label(soldiers_by_id, c.soldier_id)
        decided_pn = _soldier_label(soldiers_by_id, c.decided_by)[0] if c.decided_by else ""
        ws.append([
            str(c.id), pn, name, c.start_date.isoformat(), c.end_date.isoformat(),
            c.reason, c.status, decided_pn, c.decision_note, c.created_at.isoformat(),
        ])


def _write_soldier_field_updates(wb: openpyxl.Workbook, session: Session) -> None:
    ws = wb.create_sheet("soldier_field_updates")
    ws.append([
        "id", "soldier_personal_number", "soldier_name", "field_name", "new_value",
        "previous_value", "status", "decided_by_personal_number", "decision_note", "created_at",
    ])
    soldiers_by_id = {s.id: s for s in session.execute(select(Soldier)).scalars()}
    for u in session.execute(select(SoldierFieldUpdate)).scalars():
        pn, name = _soldier_label(soldiers_by_id, u.soldier_id)
        decided_pn = _soldier_label(soldiers_by_id, u.decided_by)[0] if u.decided_by else ""
        ws.append([
            str(u.id), pn, name, u.field_name, u.new_value, u.previous_value,
            u.status, decided_pn, u.decision_note, u.created_at.isoformat(),
        ])


def _write_soldier_enrollment_requests(wb: openpyxl.Workbook, session: Session) -> None:
    ws = wb.create_sheet("soldier_enrollment_requests")
    ws.append([
        "id", "soldier_personal_number", "soldier_name", "requested_node_name",
        "status", "decided_by_personal_number", "decision_note", "created_at",
    ])
    soldiers_by_id = {s.id: s for s in session.execute(select(Soldier)).scalars()}
    nodes_by_id = {n.id: n for n in session.execute(select(HierarchyNode)).scalars()}
    for r in session.execute(select(SoldierEnrollmentRequest)).scalars():
        pn, name = _soldier_label(soldiers_by_id, r.soldier_id)
        decided_pn = _soldier_label(soldiers_by_id, r.decided_by)[0] if r.decided_by else ""
        node = nodes_by_id.get(r.requested_node_id)
        ws.append([
            str(r.id), pn, name, node.name if node else "",
            r.status, decided_pn, r.decision_note, r.created_at.isoformat(),
        ])


def _write_soldier_exemptions(wb: openpyxl.Workbook, session: Session) -> None:
    ws = wb.create_sheet("soldier_exemptions")
    ws.append([
        "id", "soldier_personal_number", "soldier_name", "exemption_type_name",
        "start_date", "end_date", "reason", "granted_by_personal_number", "granted_at",
        "revoked_at", "revoked_by_personal_number", "revoke_reason",
    ])
    soldiers_by_id = {s.id: s for s in session.execute(select(Soldier)).scalars()}
    exemption_types_by_id = {et.id: et for et in session.execute(select(ExemptionType)).scalars()}
    for e in session.execute(select(SoldierExemption)).scalars():
        pn, name = _soldier_label(soldiers_by_id, e.soldier_id)
        et = exemption_types_by_id.get(e.exemption_type_id)
        granted_pn = _soldier_label(soldiers_by_id, e.granted_by)[0] if e.granted_by else ""
        revoked_pn = _soldier_label(soldiers_by_id, e.revoked_by)[0] if e.revoked_by else ""
        ws.append([
            str(e.id), pn, name, et.name if et else "",
            e.start_date.isoformat(), e.end_date.isoformat() if e.end_date else "",
            e.reason, granted_pn, e.granted_at.isoformat(),
            e.revoked_at.isoformat() if e.revoked_at else "", revoked_pn, e.revoke_reason,
        ])


def _write_exemption_requests(wb: openpyxl.Workbook, session: Session) -> None:
    ws = wb.create_sheet("exemption_requests")
    ws.append([
        "id", "soldier_personal_number", "soldier_name", "exemption_type_name",
        "start_date", "end_date", "reason", "status",
        "commander_approved_by_personal_number", "decided_by_personal_number",
        "decision_note", "files", "created_at",
    ])
    soldiers_by_id = {s.id: s for s in session.execute(select(Soldier)).scalars()}
    exemption_types_by_id = {et.id: et for et in session.execute(select(ExemptionType)).scalars()}
    files_by_request: dict = {}
    for f in session.execute(select(ExemptionRequestFile)).scalars():
        files_by_request.setdefault(f.exemption_request_id, []).append(f.filename)
    for r in session.execute(select(ExemptionRequest)).scalars():
        pn, name = _soldier_label(soldiers_by_id, r.soldier_id)
        et = exemption_types_by_id.get(r.exemption_type_id)
        commander_pn = _soldier_label(soldiers_by_id, r.commander_approved_by)[0] if r.commander_approved_by else ""
        decided_pn = _soldier_label(soldiers_by_id, r.decided_by)[0] if r.decided_by else ""
        files = ", ".join(files_by_request.get(r.id, []))
        ws.append([
            str(r.id), pn, name, et.name if et else "",
            r.start_date.isoformat(), r.end_date.isoformat() if r.end_date else "",
            r.reason, r.status, commander_pn, decided_pn, r.decision_note, files, r.created_at.isoformat(),
        ])


def _write_swap_requests(wb: openpyxl.Workbook, session: Session) -> None:
    ws = wb.create_sheet("swap_requests")
    ws.append([
        "id", "requesting_personal_number", "requesting_name", "target_personal_number",
        "covering_personal_number", "duty_date", "status", "reason",
        "requester_side_approved", "covering_side_approved",
        "rejected_by_personal_number", "decision_note", "approval_log", "created_at", "updated_at",
    ])
    soldiers_by_id = {s.id: s for s in session.execute(select(Soldier)).scalars()}
    decisions_by_swap: dict = {}
    for d in session.execute(select(SwapManagerApproval)).scalars():
        if not (d.approved or d.rejected):
            continue
        person = soldiers_by_id.get(d.commander_id)
        if person is None:
            continue
        outcome = "approved" if d.approved else "rejected"
        at = (d.approved_at if d.approved else d.rejected_at)
        decisions_by_swap.setdefault(d.swap_request_id, []).append(
            f"{d.side}:{d.approver_kind}:{person.personal_number}:{outcome}:{at.isoformat() if at else ''}"
        )
    for r in session.execute(select(SwapRequest)).scalars():
        requesting_pn, requesting_name = _soldier_label(soldiers_by_id, r.requesting_soldier_id)
        target_pn = _soldier_label(soldiers_by_id, r.target_soldier_id)[0] if r.target_soldier_id else ""
        covering_pn = _soldier_label(soldiers_by_id, r.covering_soldier_id)[0] if r.covering_soldier_id else ""
        rejected_pn = _soldier_label(soldiers_by_id, r.rejected_by)[0] if r.rejected_by else ""
        approval_log = ";".join(decisions_by_swap.get(r.id, []))
        ws.append([
            str(r.id), requesting_pn, requesting_name, target_pn, covering_pn,
            r.duty_date.isoformat(), r.status, r.reason,
            r.requester_side_approved, r.covering_side_approved,
            rejected_pn, r.decision_note, approval_log,
            r.created_at.isoformat(), r.updated_at.isoformat(),
        ])


_WRITERS = {
    "swap_requests": _write_swap_requests,
    "exemption_requests": _write_exemption_requests,
    "soldier_field_updates": _write_soldier_field_updates,
    "soldier_enrollment_requests": _write_soldier_enrollment_requests,
    "personal_constraints": _write_personal_constraints,
    "soldier_exemptions": _write_soldier_exemptions,
}


@router.get("/export")
def export_approvals(
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
        headers={"Content-Disposition": 'attachment; filename="approvals_export.xlsx"'},
    )
```

- [ ] **Step 3: Register the router**

In `backend/app/main.py` (or wherever routers are registered), add alongside the existing `config_export` router registration:

```python
from app.routes import approvals_export
app.include_router(approvals_export.router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest <test file from Step 1> -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/approvals_export.py backend/app/main.py <test file>
git commit -m "feat: add backend xlsx export for exemptions, constraints, and all 5 request types"
```

---

### Task 6: Frontend — export button + import tabs

**Files:**
- Modify: `frontend/src/pages/ApprovalsPage.tsx`
- Modify: `frontend/src/api/importSessions.ts` (6 new row-type interfaces, `ParsedState`/`SessionSummary.row_summary` extensions)
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx` (6 new tabs)

**Interfaces:**
- Consumes: `/approvals/export` (Task 5), the existing import-session API (already fully typed from prior work)

- [ ] **Step 1: Export button on `ApprovalsPage.tsx`**

```tsx
import { getAccessToken } from "../api/client";

async function handleExportApprovals() {
  const resp = await fetch("/api/approvals/export", {
    headers: { Authorization: `Bearer ${getAccessToken() ?? ""}` },
  });
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "approvals_export.xlsx";
  a.click();
  URL.revokeObjectURL(url);
}
```

Add a button near the page's existing tab bar: `<button onClick={() => void handleExportApprovals()}>ייצוא</button>`.

- [ ] **Step 2: Extend `frontend/src/api/importSessions.ts` with the 6 new row types**

Add 6 new interfaces mirroring the backend resolver output dicts from Task 3 exactly (one field per key in each resolver's `out.append({...})` dict), add all 6 to `ParsedState`, and add the 6 new counts to `SessionSummary.row_summary`.

- [ ] **Step 3: Add 6 new tabs to `ImportSessionReviewPage.tsx`**

Follow the exact pattern established for `duty_locations`/`hierarchy`/`soldiers` in the 2026-07-21 import-review plan: one `<thead>`/`<tbody>` block per new tab, inline-editable scalar cells via `setFieldOverride`, a details button wired to `ImportRowDetailModal` for full-field inspection, and (for `swap_requests`' `approval_log` field specifically) a read-only formatted display in the detail modal only — not inline-editable as raw text, since it's a structured log, not a simple scalar.

- [ ] **Step 4: Type-check**

Run: `npm run typecheck`
Expected: no new errors.

- [ ] **Step 5: Manual verification**

Start the dev stack, click "ייצוא" on ApprovalsPage, confirm a real xlsx downloads with all 6 sheets populated; upload it back through the Import UI, confirm all 6 new tabs appear with the right row counts and inline-editable fields.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ApprovalsPage.tsx frontend/src/api/importSessions.ts frontend/src/pages/ImportSessionReviewPage.tsx
git commit -m "feat: add approvals export button and 6 new import review tabs"
```

---

### Task 7: End-to-end round-trip tests (real xlsx, export → import)

**Files:**
- Create: `backend/app/routes/tests/test_approvals_export_import_e2e.py`

**Interfaces:**
- Consumes: `/approvals/export` (Task 5), `create_session`/`confirm_session` (Task 4)

- [ ] **Step 1: Write the failing tests**

One test per sheet, each: seed real DB rows (including decided/rejected state — for swaps, seed actual `SwapManagerApproval` decision rows too), call the export route for just that sheet, get back real xlsx bytes, feed those bytes into `create_session(..., content=xlsx_bytes, parser_id="v1_standard")` then `confirm_session(...)`, and assert the newly updated/created DB rows match the originals field-for-field. Example for `personal_constraints`:

```python
def test_personal_constraint_export_import_round_trip(admin_session, client, admin_headers):
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}")
    original = PersonalConstraint(
        soldier_id=soldier.id, start_date=date_type(2024, 6, 15), end_date=date_type(2024, 6, 16),
        reason="round trip test", status="approved", decided_by=decider.id,
        decided_at=datetime.now(UTC), decision_note="ok",
    )
    admin_session.add(original)
    admin_session.commit()

    resp = client.get("/approvals/export?sheets=personal_constraints", headers=admin_headers)
    assert resp.status_code == 200
    xlsx_bytes = resp.content

    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="roundtrip.xlsx", content=xlsx_bytes, actor=admin, parser_id="v1_standard")
    row = sess.parsed_state["personal_constraints"][0]
    assert row["action"] == "update"
    assert row["existing_id"] == str(original.id)

    confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()
    admin_session.refresh(original)

    assert original.status == "approved"
    assert original.decided_by == decider.id
    assert original.decision_note == "ok"
```

Write the parallel test for `soldier_field_updates`, `soldier_enrollment_requests`, `soldier_exemptions`, `exemption_requests`, and — the most important one — `swap_requests` with a real `approval_log`:

```python
def test_swap_request_export_import_round_trip_preserves_approval_log(admin_session, client, admin_headers):
    node = create_node(admin_session, level="unit", name=f"n_{_uid()}")
    requester = create_soldier(admin_session, personal_number=f"r_{_uid()}", hierarchy_node_id=node.id)
    covering = create_soldier(admin_session, personal_number=f"c_{_uid()}", hierarchy_node_id=node.id)
    commander = create_soldier(admin_session, personal_number=f"cm_{_uid()}")
    node.commander_id = commander.id
    assignment = _make_assignment(admin_session, soldier=requester, node=node)
    original = SwapRequest(
        duty_assignment_id=assignment.id, duty_date=assignment.start_date,
        requesting_soldier_id=requester.id, covering_soldier_id=covering.id,
        status="pending_approval", requester_side_approved=True, covering_side_approved=True,
    )
    admin_session.add(original)
    admin_session.flush()
    decision = SwapManagerApproval(
        swap_request_id=original.id, side="requester", commander_id=commander.id,
        approver_kind="commander", approved=True, approved_by=commander.id, approved_at=datetime.now(UTC),
    )
    admin_session.add(decision)
    admin_session.commit()

    resp = client.get("/approvals/export?sheets=swap_requests", headers=admin_headers)
    assert resp.status_code == 200

    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="roundtrip.xlsx", content=resp.content, actor=admin, parser_id="v1_standard")
    row = sess.parsed_state["swap_requests"][0]
    assert row["action"] == "update"
    assert len(row["approval_log"]) == 1
    assert row["approval_log"][0]["side"] == "requester"
    assert row["approval_log"][0]["outcome"] == "approved"

    confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    rows = admin_session.execute(
        select(SwapManagerApproval).where(SwapManagerApproval.swap_request_id == original.id)
    ).scalars().all()
    assert len(rows) == 1  # idempotent — re-confirming didn't duplicate the decision row
    assert rows[0].approved is True
    assert rows[0].commander_id == commander.id
```

- [ ] **Step 2: Run tests to verify they fail (or pass, if Tasks 1-6 were fully correct — either way, this is the real proof)**

Run: `pytest app/routes/tests/test_approvals_export_import_e2e.py -v`
Expected: PASS if Tasks 1-6 are correct. If any fail, that's a real bug in the export or import path surfaced by the round trip — fix the underlying code (not the test) and re-run.

- [ ] **Step 3: Run the full backend suite**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/routes/tests/test_approvals_export_import_e2e.py
git commit -m "test: add real xlsx export/import round-trip e2e tests for approvals"
```

---

## Final Check

- [ ] Run the full backend suite: `pytest -q` and `pytest --slow -q`
- [ ] Run `npm run lint` and `npm run typecheck` (frontend)
- [ ] Manually walk through: click ייצוא on ApprovalsPage, get a real file; open it and confirm 6 sheets with correct data; re-upload it via the Import UI, confirm all 6 tabs show `update` actions matching existing records; confirm the session; verify no duplicate records were created and decided/rejected state was preserved exactly.
