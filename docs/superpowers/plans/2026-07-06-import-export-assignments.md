# Import/Export Assignments Sheet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `assignments` sheet to the Excel import template/parser/review-UI/confirm flow (soldier personal_number + full_name assigned to a specific duty_shift), and add a new backend export endpoint that dumps current DB state (soldiers, duty_shifts, assignments) in the same format for a full round trip.

**Architecture:** Follows the existing session-based import architecture (`import_sessions.py` service + `ImportSessionReviewPage.tsx`), not the deprecated `/import/preview`+`/import/apply` pair. A new `ImportAssignmentRow` schema type flows through parser → resolver → review UI → confirm, exactly like `soldiers`/`duty_shifts` do today. A new `_resolve_assignments()` resolver matches each row to a soldier (by personal_number, falling back to full_name) and a shift (by composite key against existing DB shifts first, then shifts created earlier in the same import).

**Tech Stack:** Python/FastAPI/SQLAlchemy backend, openpyxl for xlsx, React/TypeScript frontend, pytest, vitest.

## Global Constraints

- Date format in all sheets: `dd.mm.yyyy` (parsed via `app/services/import_parsers/_shared_parsing.py::parse_date`).
- Boolean format: `"true"/"false"` (and Hebrew `"כן"/"נכון"`), parsed via `_shared_parsing.py::parse_bool`.
- Time format: `HH:MM` strings; default `"00:00"` (start) / `"23:59"` (end) when blank, matching `DutyShift`/`DutyAssignment` model defaults.
- All new user-facing strings (errors/warnings/UI labels) are in Hebrew, matching the existing codebase convention.
- Backend tests: `pytest -m duty -q` or targeted `pytest <path> -q` (per CLAUDE.md, don't run the full suite mid-task).
- Frontend: `npm run lint` and `npm test` from `frontend/`, run before finishing.

---

### Task 1: Schema — `ImportAssignmentRow`

**Files:**
- Modify: `backend/app/services/import_parsers/schema.py`

**Interfaces:**
- Produces: `ImportAssignmentRow` (pydantic model), and `ParsedImportData.assignments: list[ImportAssignmentRow]`, both importable from `app.services.import_parsers.schema`.

- [ ] **Step 1: Add the row model and wire it into `ParsedImportData`**

Edit `backend/app/services/import_parsers/schema.py` — add after `ImportDutyShiftRow` and extend `ParsedImportData`:

```python
class ImportAssignmentRow(BaseModel):
    source_row: int
    personal_number: str
    full_name: str
    duty_type_name: str
    duty_location_name: str
    start_date: str
    end_date: str
    start_time: str | None = None
    end_time: str | None = None
    is_reserve: bool = False
    notes: str | None = None
```

And change:

```python
class ParsedImportData(BaseModel):
    ...
    soldiers: list[ImportSoldierRow] = []
    duty_shifts: list[ImportDutyShiftRow] = []
    assignments: list[ImportAssignmentRow] = []
    parser_id: str
    parser_warnings: list[str] = []
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `cd backend && python -c "from app.services.import_parsers.schema import ImportAssignmentRow, ParsedImportData; print(ParsedImportData(parser_id='x').assignments)"`
Expected: prints `[]` with no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/import_parsers/schema.py
git commit -m "feat: add ImportAssignmentRow schema for assignments sheet"
```

---

### Task 2: Parser — real `assignments` sheet parsing (replaces legacy fallback)

**Files:**
- Modify: `backend/app/services/import_parsers/v1_standard.py`
- Modify: `backend/app/services/tests/test_import_parser_v1.py`

**Interfaces:**
- Consumes: `ImportAssignmentRow` from Task 1.
- Produces: `V1StandardParser().parse(wb).assignments: list[ImportAssignmentRow]`.

Today, `v1_standard.py` only reads `assignments` as a *fallback source for duty_shifts* when `duty_shifts` is absent (lines 112-128), converting rows into synthetic `duty_shifts` with `required_count=1`. This task replaces that with real, independent parsing of an `assignments` sheet into `ImportAssignmentRow`s — always parsed if present, regardless of whether `duty_shifts` is also present.

- [ ] **Step 1: Write the failing tests**

In `backend/app/services/tests/test_import_parser_v1.py`, replace the existing `test_legacy_assignments_sheet_falls_back_to_duty_shifts` test (lines 126-140) with:

```python
def _wb_with_assignments_sheet(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("assignments")
    ws.append([
        "personal_number", "full_name", "duty_type_name", "duty_location_name",
        "start_date", "end_date", "start_time", "end_time", "is_reserve", "notes",
    ])
    for r in rows:
        ws.append(r)
    return wb


def test_parses_assignments_sheet_row():
    wb = _wb_with_assignments_sheet([
        ["12345", "ישראל ישראלי", "שמירה", "שער ראשי",
         "15.06.2024", "16.06.2024", "20:00", "06:00", "true", "הערה"],
    ])
    data = V1StandardParser().parse(wb)
    assert len(data.assignments) == 1
    row = data.assignments[0]
    assert row.personal_number == "12345"
    assert row.full_name == "ישראל ישראלי"
    assert row.duty_type_name == "שמירה"
    assert row.duty_location_name == "שער ראשי"
    assert row.start_date == "2024-06-15"
    assert row.end_date == "2024-06-16"
    assert row.start_time == "20:00"
    assert row.end_time == "06:00"
    assert row.is_reserve is True
    assert row.notes == "הערה"


def test_assignments_sheet_does_not_produce_synthetic_duty_shifts():
    wb = _wb_with_assignments_sheet([
        ["12345", "ישראל ישראלי", "שמירה", "שער ראשי",
         "15.06.2024", "16.06.2024", "", "", "false", ""],
    ])
    data = V1StandardParser().parse(wb)
    assert data.duty_shifts == []
    assert not any("assignments" in w for w in data.parser_warnings)


def test_assignments_sheet_absent_gives_empty_list():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    data = V1StandardParser().parse(wb)
    assert data.assignments == []


def test_assignments_and_duty_shifts_both_present_both_parsed():
    wb = _wb_with_assignments_sheet([
        ["12345", "ישראל ישראלי", "שמירה", "שער ראשי",
         "15.06.2024", "16.06.2024", "", "", "false", ""],
    ])
    ws = wb.create_sheet("duty_shifts")
    ws.append([
        "duty_type_name", "duty_location_name", "start_date", "end_date",
        "start_time", "end_time", "required_count", "node_quotas", "notes",
    ])
    ws.append(["שמירה", "שער ראשי", "15.06.2024", "16.06.2024", "", "", 2, "", ""])

    data = V1StandardParser().parse(wb)
    assert len(data.assignments) == 1
    assert len(data.duty_shifts) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_import_parser_v1.py -v -k "assignments"`
Expected: FAIL — `data.assignments` doesn't exist yet / assignments sheet still converted to duty_shifts.

- [ ] **Step 3: Replace the fallback logic with real parsing**

Edit `backend/app/services/import_parsers/v1_standard.py`. Change the import line:

```python
from app.services.import_parsers.schema import (
    ImportAssignmentRow,
    ImportDutyShiftRow,
    ImportNodeQuota,
    ImportSoldierRow,
    ParsedImportData,
)
```

Replace lines 71-154 (the `V1StandardParser` class body from the docstring through `return ParsedImportData(...)`) with:

```python
class V1StandardParser:
    """Standard v1 layout: `soldiers`, `duty_shifts`, `assignments`.

    Shift templates are not importable via Excel — they're managed only
    through the system UI. A `shift_templates` sheet, if present, is ignored.
    """

    id = "v1_standard"
    label = "תבנית סטנדרטית (v1)"

    def detect(self, wb: openpyxl.Workbook) -> float:
        matches = KNOWN_SHEETS & set(wb.sheetnames)
        if not matches:
            return 0.0
        return min(1.0, 0.5 + 0.2 * len(matches))

    def parse(self, wb: openpyxl.Workbook) -> ParsedImportData:
        warnings: list[str] = []

        soldiers = [
            ImportSoldierRow(
                source_row=r["_row"],
                personal_number=str(r.get("personal_number") or "").strip(),
                full_name=str(r.get("full_name") or "").strip(),
                rank=str(r.get("rank") or "").strip() or None,
                gender=str(r.get("gender") or "").strip() or None,
                is_officer=_parse_bool(r.get("is_officer")),
                hierarchy_node_name=str(r.get("hierarchy_node_name") or "").strip() or None,
                enrolled_at=_parse_date(r.get("enrolled_at")),
                enlistment_date=_parse_date(r.get("enlistment_date")),
                phone=str(r.get("phone") or "").strip() or None,
                email=str(r.get("email") or "").strip() or None,
            )
            for r in _sheet_rows(wb, "soldiers")
        ]

        duty_shifts = []
        for r in _sheet_rows(wb, "duty_shifts"):
            node_quotas, node_quota_warnings = _parse_node_quotas(r.get("node_quotas"), r["_row"])
            warnings.extend(node_quota_warnings)
            duty_shifts.append(
                ImportDutyShiftRow(
                    source_row=r["_row"],
                    duty_type_name=str(r.get("duty_type_name") or "").strip(),
                    duty_location_name=str(r.get("duty_location_name") or "").strip(),
                    start_date=_parse_date(r.get("start_date")) or "",
                    end_date=_parse_date(r.get("end_date")) or "",
                    start_time=str(r.get("start_time") or "").strip() or None,
                    end_time=str(r.get("end_time") or "").strip() or None,
                    required_count=int(r.get("required_count") or 1),
                    node_quotas=node_quotas,
                    notes=str(r.get("notes") or "").strip() or None,
                )
            )

        assignments = [
            ImportAssignmentRow(
                source_row=r["_row"],
                personal_number=str(r.get("personal_number") or "").strip(),
                full_name=str(r.get("full_name") or "").strip(),
                duty_type_name=str(r.get("duty_type_name") or "").strip(),
                duty_location_name=str(r.get("duty_location_name") or "").strip(),
                start_date=_parse_date(r.get("start_date")) or "",
                end_date=_parse_date(r.get("end_date")) or "",
                start_time=str(r.get("start_time") or "").strip() or None,
                end_time=str(r.get("end_time") or "").strip() or None,
                is_reserve=_parse_bool(r.get("is_reserve")) or False,
                notes=str(r.get("notes") or "").strip() or None,
            )
            for r in _sheet_rows(wb, "assignments")
        ]

        return ParsedImportData(
            soldiers=soldiers,
            duty_shifts=duty_shifts,
            assignments=assignments,
            parser_id=self.id,
            parser_warnings=warnings,
        )


register(V1StandardParser())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_import_parser_v1.py -v`
Expected: all PASS (including the pre-existing `duty_shifts`/`soldiers` tests, which are unaffected).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/import_parsers/v1_standard.py backend/app/services/tests/test_import_parser_v1.py
git commit -m "feat: parse assignments sheet directly instead of converting to duty_shifts"
```

---

### Task 3: Template — add `assignments` sheet to `GET /import/template`

**Files:**
- Modify: `backend/app/routes/import_excel.py`
- Modify: `backend/tests/integration/test_import_excel.py`
- Modify: `frontend/src/pages/ImportUploadPage.tsx`

**Interfaces:**
- No new interfaces; extends the existing `download_template()` endpoint's output.

- [ ] **Step 1: Write the failing test**

In `backend/tests/integration/test_import_excel.py`, extend `test_template_download` (replace it):

```python
def test_template_download(client, admin_session):
    node = create_node(admin_session, level="branch", name="ie_node_004")
    dm = create_soldier(admin_session, personal_number="ie_dm_004", role="duty_manager", hierarchy_node_id=node.id)
    token = auth_headers(dm)["Authorization"].split(" ", 1)[1]
    resp = client.get("/api/import/template", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert "spreadsheetml" in resp.headers["content-type"]

    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert set(wb.sheetnames) == {"soldiers", "duty_shifts", "assignments"}
    headers = [c.value for c in next(wb["assignments"].iter_rows(min_row=1, max_row=1))]
    assert headers == [
        "personal_number", "full_name", "duty_type_name", "duty_location_name",
        "start_date", "end_date", "start_time", "end_time", "is_reserve", "notes",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_import_excel.py::test_template_download -v`
Expected: FAIL — `wb.sheetnames` is `{"soldiers", "duty_shifts"}`, no `assignments`.

- [ ] **Step 3: Add the sheet to the template**

Edit `backend/app/routes/import_excel.py`. Update the `download_template` docstring and add the sheet after the `ws_d` block (after line 357, before `buf = io.BytesIO()`):

```python
    ws_a = wb.create_sheet("assignments")
    ws_a.append(["personal_number", "full_name", "duty_type_name", "duty_location_name",
                  "start_date", "end_date", "start_time", "end_time", "is_reserve", "notes"])
    ws_a.append(["12345", "ישראל ישראלי", "שמירה", "שער ראשי", "15.06.2024", "16.06.2024", "20:00", "06:00", "false", ""])
    ws_a.append(["23456", "משה כהן", "שמירה", "שער ראשי", "15.06.2024", "16.06.2024", "20:00", "06:00", "true", "מחליף תורן"])
```

Update the function docstring (lines 327-332):

```python
def download_template():
    """Download an example workbook for the active import pipeline.

    Matches the `v1_standard` parser's expected sheets (`soldiers`,
    `duty_shifts`, `assignments`) — see
    app/services/import_parsers/v1_standard.py. Shift templates are
    intentionally not included: they're created only through the system UI
    (app/routes/shift_templates.py), not via Excel import.
    """
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_import_excel.py::test_template_download -v`
Expected: PASS.

- [ ] **Step 5: Update the upload page copy**

Edit `frontend/src/pages/ImportUploadPage.tsx` line 43-45:

```tsx
          <p className="text-gray-600 dark:text-gray-400 text-sm">
            העלה קובץ Excel עם גיליונות:{" "}
            <code>soldiers</code>, <code>duty_shifts</code>, <code>assignments</code>
          </p>
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/import_excel.py backend/tests/integration/test_import_excel.py frontend/src/pages/ImportUploadPage.tsx
git commit -m "feat: add assignments sheet to import template"
```

---

### Task 4: Soldier resolution — personal_number → full_name fallback

**Files:**
- Modify: `backend/app/services/import_sessions.py` (`_resolve_soldiers`, `confirm_session`)
- Modify: `backend/app/services/tests/test_import_sessions_service.py`

**Interfaces:**
- Produces: each row dict from `_resolve_soldiers()` now also has a `"warnings": list[str]` key (previously absent). `confirm_session()`'s soldier-update branch now also writes `s.personal_number`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/app/services/tests/test_import_sessions_service.py`:

```python
def test_soldier_fallback_matches_by_full_name_when_personal_number_unknown(admin_session):
    existing = create_soldier(admin_session, personal_number=f"old_pn_{_uid()}")
    admin_session.commit()

    wb = _wb_with_soldiers([
        [f"new_pn_{_uid()}", existing.full_name, "", "", "", "", "", "", "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")

    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row = sess.parsed_state["soldiers"][0]
    assert row["action"] == "update"
    assert row["existing_id"] == str(existing.id)
    assert any("שם" in w for w in row["warnings"])


def test_soldier_fallback_ambiguous_full_name_errors(admin_session):
    from app.auth.password import hash_password
    from app.db.models import Soldier

    dup_name = f"Dup Name {_uid()}"
    s1 = Soldier(personal_number=f"pn1_{_uid()}", full_name=dup_name, password_hash=hash_password("x"))
    s2 = Soldier(personal_number=f"pn2_{_uid()}", full_name=dup_name, password_hash=hash_password("x"))
    admin_session.add_all([s1, s2])
    admin_session.commit()

    wb = _wb_with_soldiers([
        [f"unknown_pn_{_uid()}", dup_name, "", "", "", "", "", "", "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")

    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row = sess.parsed_state["soldiers"][0]
    assert row["action"] == "error"
    assert any("חד משמעי" in e for e in row["errors"])


def test_soldier_fallback_updates_personal_number_on_confirm(admin_session):
    existing = create_soldier(admin_session, personal_number=f"old_pn_{_uid()}")
    admin_session.commit()
    new_pn = f"new_pn_{_uid()}"

    wb = _wb_with_soldiers([
        [new_pn, existing.full_name, "", "", "", "", "", "", "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    admin_session.commit()

    result = confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()
    assert result["updated"] == 1

    admin_session.refresh(existing)
    assert existing.personal_number == new_pn
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_import_sessions_service.py -v -k "fallback"`
Expected: FAIL — `row["action"]` is `"new"` (no fallback yet), `row["warnings"]` KeyError, `existing.personal_number` unchanged.

- [ ] **Step 3: Implement the fallback in `_resolve_soldiers`**

Edit `backend/app/services/import_sessions.py`. Replace the body of `_resolve_soldiers` (lines 31-104):

```python
def _resolve_soldiers(
    session: Session,
    data: ParsedImportData,
    actor: Soldier,
    node_by_name: dict[str, str] | None = None,
    node_by_row: dict[str, str] | None = None,
) -> list[dict]:
    node_by_name = node_by_name or {}
    node_by_row = node_by_row or {}
    existing_by_pn = {
        s.personal_number: s for s in session.execute(select(Soldier)).scalars()
    }
    existing_by_full_name: dict[str, list[Soldier]] = {}
    for s in existing_by_pn.values():
        existing_by_full_name.setdefault(s.full_name, []).append(s)
    nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}

    out = []
    for row in data.soldiers:
        errors: list[str] = []
        warnings: list[str] = []
        if not row.personal_number:
            errors.append("חסר מספר אישי")
        if not row.full_name:
            errors.append("חסר שם מלא")

        node = None
        if row.hierarchy_node_name:
            row_key = f"soldiers:{row.source_row}"
            mapped_id = node_by_row.get(row_key) or node_by_name.get(row.hierarchy_node_name)
            if mapped_id:
                try:
                    node = session.get(HierarchyNode, uuid.UUID(mapped_id))
                except ValueError:
                    pass
            if node is None:
                node = nodes_by_name.get(row.hierarchy_node_name)
            if node is None:
                errors.append(f"יחידה לא מזוהה '{row.hierarchy_node_name}'")

        existing = existing_by_pn.get(row.personal_number) if row.personal_number else None
        if existing is None and row.personal_number and row.full_name:
            candidates = existing_by_full_name.get(row.full_name, [])
            if len(candidates) == 1:
                existing = candidates[0]
                warnings.append(
                    f"נמצא לפי שם — מספר אישי עודכן מ-'{existing.personal_number}' ל-'{row.personal_number}'"
                )
            elif len(candidates) > 1:
                errors.append(
                    f"שם '{row.full_name}' אינו חד משמעי (מספר אישי '{row.personal_number}' לא נמצא)"
                )

        if errors:
            action = "error"
        elif existing is not None:
            action = "update"
        else:
            action = "new"

        if action != "error" and node is not None:
            # Per-row scope check: re-runs scope_root_ids(session, actor) on every
            # iteration instead of hoisting it out of the loop. Fine for typical
            # single-Excel-import row counts; if import volumes grow significantly,
            # this is the first place to optimize (precompute scope_root_ids once
            # and inline the subtree check).
            if actor.role != "admin" and not is_node_in_actor_scope(
                session=session, actor=actor, node_id=node.id
            ):
                action = "out_of_scope"

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "warnings": warnings,
            "personal_number": row.personal_number,
            "full_name": row.full_name,
            "rank": row.rank,
            "gender": row.gender,
            "is_officer": row.is_officer,
            "hierarchy_node_id": str(node.id) if node is not None else None,
            "hierarchy_node_name": row.hierarchy_node_name,
            "enrolled_at": row.enrolled_at,
            "enlistment_date": row.enlistment_date,
            "phone": row.phone,
            "email": row.email,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out
```

(Only additions: `existing_by_full_name` lookup, the fallback block, `warnings` list and its key in the output dict.)

- [ ] **Step 4: Make `confirm_session` write the corrected `personal_number` on update**

In `confirm_session`, in the `elif effective == "update" and row.get("existing_id"):` branch (around line 385-407), add the personal_number write as the first field update:

```python
            elif effective == "update" and row.get("existing_id"):
                s = session.get(Soldier, uuid.UUID(row["existing_id"]))
                if s is not None:
                    s.personal_number = row["personal_number"]
                    s.full_name = row["full_name"]
                    if row.get("rank") is not None:
```

(Only the added `s.personal_number = row["personal_number"]` line; everything else in that branch is unchanged.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_import_sessions_service.py -v`
Expected: all PASS, including the 3 new tests and all pre-existing ones.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/import_sessions.py backend/app/services/tests/test_import_sessions_service.py
git commit -m "feat: fall back to full_name match when personal_number is unrecognized"
```

---

### Task 5: Assignment resolution — `_resolve_assignments`

**Files:**
- Modify: `backend/app/services/import_sessions.py` (new `_resolve_assignments`, wire into `_resolve_and_score`)
- Modify: `backend/app/services/tests/test_import_sessions_service.py`

**Interfaces:**
- Consumes: `ParsedImportData.assignments` (Task 1/2), the `duty_shifts` result list produced by `_resolve_duty_shifts` (existing function, unchanged signature/output).
- Produces: `_resolve_assignments(session, data, actor, resolved_duty_shifts) -> list[dict]`, each dict having keys: `row, action, errors, warnings, personal_number, full_name, duty_type_name, duty_location_name, start_date, end_date, start_time, end_time, is_reserve, notes, resolved_soldier_id, resolved_duty_shift_id, matched_session_row`. Wired into `_resolve_and_score()`'s returned dict under key `"assignments"`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/app/services/tests/test_import_sessions_service.py`:

```python
def _wb_with_assignments(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("assignments")
    ws.append([
        "personal_number", "full_name", "duty_type_name", "duty_location_name",
        "start_date", "end_date", "start_time", "end_time", "is_reserve", "notes",
    ])
    for r in rows:
        ws.append(r)
    return wb


def _wb_with_duty_shifts_and_assignments(duty_shift_rows, assignment_rows):
    wb = _wb_with_duty_shifts(duty_shift_rows)
    ws = wb.create_sheet("assignments")
    ws.append([
        "personal_number", "full_name", "duty_type_name", "duty_location_name",
        "start_date", "end_date", "start_time", "end_time", "is_reserve", "notes",
    ])
    for r in assignment_rows:
        ws.append(r)
    return wb


def test_assignment_matches_existing_shift(admin_session):
    from app.db.models import DutyShift

    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_type(2024, 6, 15), end_date=date_type(2024, 6, 16),
        required_count=2,
    )
    admin_session.add(shift)
    admin_session.flush()
    soldier = create_soldier(admin_session, personal_number=f"sol_{_uid()}")
    admin_session.commit()

    wb = _wb_with_assignments([
        [soldier.personal_number, soldier.full_name, dt.name, loc.name,
         "15.06.2024", "16.06.2024", "00:00", "23:59", "false", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )

    row = sess.parsed_state["assignments"][0]
    assert row["action"] == "new"
    assert row["resolved_duty_shift_id"] == str(shift.id)
    assert row["matched_session_row"] is None


def test_assignment_matches_session_duty_shifts_row(admin_session):
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    soldier = create_soldier(admin_session, personal_number=f"sol_{_uid()}")
    admin_session.commit()

    wb = _wb_with_duty_shifts_and_assignments(
        [[dt.name, loc.name, "15.06.2024", "16.06.2024", "", "", 2, "", ""]],
        [[soldier.personal_number, soldier.full_name, dt.name, loc.name,
          "15.06.2024", "16.06.2024", "", "", "false", ""]],
    )
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )

    row = sess.parsed_state["assignments"][0]
    assert row["action"] == "new"
    assert row["resolved_duty_shift_id"] is None
    assert row["matched_session_row"] == sess.parsed_state["duty_shifts"][0]["row"]


def test_assignment_full_name_mismatch_errors(admin_session):
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    soldier = create_soldier(admin_session, personal_number=f"sol_{_uid()}")
    admin_session.commit()

    wb = _wb_with_assignments([
        [soldier.personal_number, "Wrong Name", dt.name, loc.name,
         "15.06.2024", "16.06.2024", "", "", "false", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row = sess.parsed_state["assignments"][0]
    assert row["action"] == "error"
    assert any("שם מלא" in e for e in row["errors"])


def test_assignment_personal_number_unknown_falls_back_to_full_name(admin_session):
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    soldier = create_soldier(admin_session, personal_number=f"sol_{_uid()}")
    admin_session.commit()

    wb = _wb_with_assignments([
        [f"unknown_{_uid()}", soldier.full_name, dt.name, loc.name,
         "15.06.2024", "16.06.2024", "", "", "false", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row = sess.parsed_state["assignments"][0]
    assert row["action"] == "error"  # no matching shift exists for this dt/loc/dates
    # Soldier itself resolved via fallback despite no shift match:
    assert row["resolved_soldier_id"] == str(soldier.id)
    assert any("נמצא לפי שם" in w for w in row["warnings"])


def test_assignment_ambiguous_full_name_errors(admin_session):
    from app.auth.password import hash_password
    from app.db.models import Soldier

    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    dup_name = f"Dup {_uid()}"
    s1 = Soldier(personal_number=f"pn1_{_uid()}", full_name=dup_name, password_hash=hash_password("x"))
    s2 = Soldier(personal_number=f"pn2_{_uid()}", full_name=dup_name, password_hash=hash_password("x"))
    admin_session.add_all([s1, s2])
    admin_session.commit()

    wb = _wb_with_assignments([
        [f"unknown_{_uid()}", dup_name, dt.name, loc.name,
         "15.06.2024", "16.06.2024", "", "", "false", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row = sess.parsed_state["assignments"][0]
    assert row["action"] == "error"
    assert any("חד משמעי" in e for e in row["errors"])


def test_assignment_duplicate_is_skipped(admin_session):
    from app.db.models import DutyAssignment, DutyShift

    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_type(2024, 6, 15), end_date=date_type(2024, 6, 16),
        required_count=2,
    )
    admin_session.add(shift)
    admin_session.flush()
    soldier = create_soldier(admin_session, personal_number=f"sol_{_uid()}")
    admin_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        duty_shift_id=shift.id, start_date=shift.start_date, end_date=shift.end_date,
    ))
    admin_session.commit()

    wb = _wb_with_assignments([
        [soldier.personal_number, soldier.full_name, dt.name, loc.name,
         "15.06.2024", "16.06.2024", "00:00", "23:59", "false", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row = sess.parsed_state["assignments"][0]
    assert row["action"] == "skip"


def test_assignment_over_capacity_warns_but_allows(admin_session):
    from app.db.models import DutyAssignment, DutyShift

    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_type(2024, 6, 15), end_date=date_type(2024, 6, 16),
        required_count=1,
    )
    admin_session.add(shift)
    admin_session.flush()
    already_assigned = create_soldier(admin_session, personal_number=f"sol_a_{_uid()}")
    admin_session.add(DutyAssignment(
        soldier_id=already_assigned.id, duty_type_id=dt.id, duty_location_id=loc.id,
        duty_shift_id=shift.id, start_date=shift.start_date, end_date=shift.end_date,
    ))
    new_soldier = create_soldier(admin_session, personal_number=f"sol_b_{_uid()}")
    admin_session.commit()

    wb = _wb_with_assignments([
        [new_soldier.personal_number, new_soldier.full_name, dt.name, loc.name,
         "15.06.2024", "16.06.2024", "00:00", "23:59", "false", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row = sess.parsed_state["assignments"][0]
    assert row["action"] == "new"
    assert any("1/1" in w for w in row["warnings"])
```

Add `from datetime import date as date_type` to the top-level imports of the test file if not already present (check first — it is not currently imported there).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_import_sessions_service.py -v -k "assignment"`
Expected: FAIL — `KeyError: 'assignments'` (not yet in `parsed_state`).

- [ ] **Step 3: Implement `_resolve_assignments` and wire it in**

Edit `backend/app/services/import_sessions.py`. Add `DutyAssignment` to the model imports (top of file):

```python
from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyShift,
    DutyType,
    HierarchyNode,
    ImportSession,
    Soldier,
)
```

Add the new function after `_resolve_shift_templates` (before `_resolve_and_score`):

```python
def _resolve_assignments(
    session: Session,
    data: ParsedImportData,
    actor: Soldier,
    resolved_duty_shifts: list[dict],
) -> list[dict]:
    def _default_time(value: str | None, default: str) -> str:
        return value if value else default

    soldiers_by_pn = {s.personal_number: s for s in session.execute(select(Soldier)).scalars()}
    soldiers_by_full_name: dict[str, list[Soldier]] = {}
    for s in soldiers_by_pn.values():
        soldiers_by_full_name.setdefault(s.full_name, []).append(s)
    duty_types_by_name = {dt.name: dt for dt in session.execute(select(DutyType)).scalars()}
    locations_by_name = {loc.name: loc for loc in session.execute(select(DutyLocation)).scalars()}

    existing_shifts = session.execute(select(DutyShift)).scalars().all()
    existing_shift_by_key: dict[tuple, DutyShift] = {}
    for shift in existing_shifts:
        key = (
            shift.duty_type_id, shift.duty_location_id,
            shift.start_date.isoformat(), shift.end_date.isoformat(),
            shift.start_time, shift.end_time,
        )
        existing_shift_by_key[key] = shift

    session_shift_by_key: dict[tuple, dict] = {}
    for shift_row in resolved_duty_shifts:
        if (
            shift_row["action"] != "new"
            or not shift_row.get("resolved_duty_type_id")
            or not shift_row.get("resolved_duty_location_id")
        ):
            continue
        key = (
            uuid.UUID(shift_row["resolved_duty_type_id"]),
            uuid.UUID(shift_row["resolved_duty_location_id"]),
            shift_row["start_date"], shift_row["end_date"],
            _default_time(shift_row.get("start_time"), "00:00"),
            _default_time(shift_row.get("end_time"), "23:59"),
        )
        session_shift_by_key[key] = shift_row

    existing_assignment_pairs = {
        (a.soldier_id, a.duty_shift_id)
        for a in session.execute(select(DutyAssignment)).scalars()
        if a.duty_shift_id is not None
    }
    running_count: dict[str, int] = {}
    for (_, shift_id) in existing_assignment_pairs:
        key = f"existing:{shift_id}"
        running_count[key] = running_count.get(key, 0) + 1

    out = []
    for row in data.assignments:
        errors: list[str] = []
        warnings: list[str] = []

        soldier = soldiers_by_pn.get(row.personal_number) if row.personal_number else None
        if soldier is not None:
            if soldier.full_name != row.full_name:
                errors.append(
                    f"שם מלא '{row.full_name}' אינו תואם לחייל עם מספר אישי "
                    f"'{row.personal_number}' ('{soldier.full_name}')"
                )
        else:
            candidates = soldiers_by_full_name.get(row.full_name, []) if row.full_name else []
            if len(candidates) == 1:
                soldier = candidates[0]
                warnings.append(f"נמצא לפי שם — מספר אישי '{row.personal_number}' לא נמצא")
            elif len(candidates) > 1:
                errors.append(
                    f"מספר אישי '{row.personal_number}' לא נמצא ושם '{row.full_name}' אינו חד משמעי"
                )
            else:
                errors.append(
                    f"לא נמצא חייל עם מספר אישי '{row.personal_number}' או שם '{row.full_name}'"
                )

        duty_type = duty_types_by_name.get(row.duty_type_name) if row.duty_type_name else None
        if duty_type is None:
            errors.append(f"סוג תורנות לא מזוהה '{row.duty_type_name}'")
        location = locations_by_name.get(row.duty_location_name) if row.duty_location_name else None
        if location is None:
            errors.append(f"מיקום תורנות לא מזוהה '{row.duty_location_name}'")

        resolved_duty_shift_id: str | None = None
        matched_session_row: int | None = None
        shift_key_str: str | None = None
        required_count: int | None = None
        if duty_type is not None and location is not None and row.start_date and row.end_date:
            key = (
                duty_type.id, location.id, row.start_date, row.end_date,
                _default_time(row.start_time, "00:00"),
                _default_time(row.end_time, "23:59"),
            )
            existing_match = existing_shift_by_key.get(key)
            session_match = session_shift_by_key.get(key)
            if existing_match is not None:
                resolved_duty_shift_id = str(existing_match.id)
                shift_key_str = f"existing:{existing_match.id}"
                required_count = existing_match.required_count
            elif session_match is not None:
                matched_session_row = session_match["row"]
                shift_key_str = f"session_row:{matched_session_row}"
                required_count = session_match["required_count"]
            else:
                errors.append("לא נמצאה משמרת תואמת (סוג תורנות, מיקום, תאריכים ושעות)")

        action = "error" if errors else "new"

        if action == "new" and soldier is not None and actor.role != "admin":
            if soldier.hierarchy_node_id is None or not is_node_in_actor_scope(
                session=session, actor=actor, node_id=soldier.hierarchy_node_id
            ):
                action = "out_of_scope"

        if (
            action == "new"
            and soldier is not None
            and resolved_duty_shift_id is not None
            and (soldier.id, uuid.UUID(resolved_duty_shift_id)) in existing_assignment_pairs
        ):
            action = "skip"

        if action == "new" and shift_key_str is not None and required_count is not None:
            current = running_count.get(shift_key_str, 0)
            if current >= required_count:
                warnings.append(f"למשמרת כבר משויכים {current}/{required_count} חיילים")
            running_count[shift_key_str] = current + 1

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "warnings": warnings,
            "personal_number": row.personal_number,
            "full_name": row.full_name,
            "duty_type_name": row.duty_type_name,
            "duty_location_name": row.duty_location_name,
            "start_date": row.start_date,
            "end_date": row.end_date,
            "start_time": row.start_time,
            "end_time": row.end_time,
            "is_reserve": row.is_reserve,
            "notes": row.notes,
            "resolved_soldier_id": str(soldier.id) if soldier is not None else None,
            "resolved_duty_shift_id": resolved_duty_shift_id,
            "matched_session_row": matched_session_row,
        })
    return out
```

Then change `_resolve_and_score` to wire it in:

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
    duty_shifts = _resolve_duty_shifts(session, data, actor, dt_by_name, dt_by_row, node_by_name, node_by_row)
    return {
        "soldiers": _resolve_soldiers(session, data, actor, node_by_name, node_by_row),
        "duty_shifts": duty_shifts,
        "shift_templates": _resolve_shift_templates(session, data, dt_by_name, dt_by_row),
        "assignments": _resolve_assignments(session, data, actor, duty_shifts),
        "parser_id": data.parser_id,
        "parser_warnings": data.parser_warnings,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_import_sessions_service.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/import_sessions.py backend/app/services/tests/test_import_sessions_service.py
git commit -m "feat: resolve assignments sheet rows to soldiers and shifts"
```

---

### Task 6: Confirm — create `DutyAssignment` rows

**Files:**
- Modify: `backend/app/services/import_sessions.py` (`confirm_session`)
- Modify: `backend/app/services/tests/test_import_sessions_service.py`

**Interfaces:**
- Consumes: `state["assignments"]` rows from Task 5 (keys `resolved_soldier_id`, `resolved_duty_shift_id`, `matched_session_row`, etc.), and `state["duty_shifts"]` rows.
- Produces: `confirm_session()` result dict gains assignment counts folded into `created`/`skipped`/`errors` (same shape as today, no new top-level keys), and `import_session.created_links["assignments"]: list[str]`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/app/services/tests/test_import_sessions_service.py`:

```python
def test_confirm_session_creates_assignment_against_existing_shift(admin_session):
    from app.db.models import DutyAssignment, DutyShift

    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_type(2024, 6, 15), end_date=date_type(2024, 6, 16),
        required_count=2,
    )
    admin_session.add(shift)
    admin_session.flush()
    soldier = create_soldier(admin_session, personal_number=f"sol_{_uid()}")
    admin_session.commit()

    wb = _wb_with_assignments([
        [soldier.personal_number, soldier.full_name, dt.name, loc.name,
         "15.06.2024", "16.06.2024", "00:00", "23:59", "true", "note"],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    admin_session.commit()

    result = confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    assert result["created"] == 1
    assert result["errors"] == []
    assert len(sess.created_links["assignments"]) == 1

    created = admin_session.get(DutyAssignment, uuid.UUID(sess.created_links["assignments"][0]))
    assert created is not None
    assert created.soldier_id == soldier.id
    assert created.duty_shift_id == shift.id
    assert created.is_reserve is True
    assert created.notes == "note"


def test_confirm_session_creates_assignment_against_session_created_shift(admin_session):
    from app.db.models import DutyAssignment

    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    soldier = create_soldier(admin_session, personal_number=f"sol_{_uid()}")
    admin_session.commit()

    wb = _wb_with_duty_shifts_and_assignments(
        [[dt.name, loc.name, "15.06.2024", "16.06.2024", "", "", 2, "", ""]],
        [[soldier.personal_number, soldier.full_name, dt.name, loc.name,
          "15.06.2024", "16.06.2024", "", "", "false", ""]],
    )
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    admin_session.commit()

    result = confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    assert result["created"] == 2  # 1 duty_shift + 1 assignment
    assert result["errors"] == []
    created_shift_id = uuid.UUID(sess.created_links["duty_shifts"][0])
    created_assignment = admin_session.get(
        DutyAssignment, uuid.UUID(sess.created_links["assignments"][0])
    )
    assert created_assignment.duty_shift_id == created_shift_id


def test_confirm_session_assignment_matched_shift_skipped_errors_gracefully(admin_session):
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    soldier = create_soldier(admin_session, personal_number=f"sol_{_uid()}")
    admin_session.commit()

    wb = _wb_with_duty_shifts_and_assignments(
        [[dt.name, loc.name, "15.06.2024", "16.06.2024", "", "", 2, "", ""]],
        [[soldier.personal_number, soldier.full_name, dt.name, loc.name,
          "15.06.2024", "16.06.2024", "", "", "false", ""]],
    )
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    shift_row_num = sess.parsed_state["duty_shifts"][0]["row"]
    set_selections(admin_session, session_id=sess.id, selections={
        "duty_shifts": {str(shift_row_num): "skip"},
    })
    admin_session.commit()

    result = confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    assert result["created"] == 0
    assert len(result["errors"]) == 1
    assert result["errors"][0]["type"] == "assignments"
    assert sess.created_links["assignments"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_import_sessions_service.py -v -k "confirm_session_creates_assignment or confirm_session_assignment_matched"`
Expected: FAIL — `sess.created_links["assignments"]` KeyError (not created yet).

- [ ] **Step 3: Implement assignment creation in `confirm_session`**

Edit `backend/app/services/import_sessions.py`. In `confirm_session`, add `shift_row_to_id` tracking to the duty_shifts loop, and a new assignments loop after it. Replace from `created_duty_shifts: list[str] = []` (initial declarations) through the end of the duty_shifts loop, then add the assignments loop:

```python
    created = 0
    updated = 0
    skipped = 0
    errors: list[dict] = []
    created_soldiers: list[str] = []
    created_duty_shifts: list[str] = []
    created_assignments: list[str] = []
    shift_row_to_id: dict[int, uuid.UUID] = {}
```

(This replaces the existing declarations block near the top of `confirm_session`.)

In the duty_shifts loop, right after `created_duty_shifts.append(str(shift.id))` (inside the `try`, after the nested transaction block), add:

```python
            created += 1
            created_duty_shifts.append(str(shift.id))
            shift_row_to_id[row["row"]] = shift.id
```

Then, after the duty_shifts `for` loop ends (before the `import_session.created_links = {...}` assignment), add:

```python
    # ── Assignments ─────────────────────────────────────────────────────
    for row in state.get("assignments", []):
        effective = _effective_action(selections, "assignments", row)
        if row["action"] in ("error", "out_of_scope") or effective == "skip":
            skipped += 1
            continue
        if effective != "new":
            skipped += 1
            continue
        try:
            if row.get("resolved_duty_shift_id"):
                duty_shift_id = uuid.UUID(row["resolved_duty_shift_id"])
            elif row.get("matched_session_row") is not None:
                mapped = shift_row_to_id.get(row["matched_session_row"])
                if mapped is None:
                    errors.append({
                        "row": row["row"], "type": "assignments",
                        "error": "המשמרת המתאימה לא נוצרה (דולגה או נכשלה)",
                    })
                    continue
                duty_shift_id = mapped
            else:
                errors.append({
                    "row": row["row"], "type": "assignments", "error": "לא נמצאה משמרת תואמת",
                })
                continue

            shift = session.get(DutyShift, duty_shift_id)
            assignment = DutyAssignment(
                soldier_id=uuid.UUID(row["resolved_soldier_id"]),
                duty_type_id=shift.duty_type_id,
                duty_location_id=shift.duty_location_id,
                duty_shift_id=duty_shift_id,
                start_date=shift.start_date,
                end_date=shift.end_date,
                is_reserve=row.get("is_reserve") or False,
                notes=row.get("notes"),
            )
            if shift.start_time:
                assignment.start_time = shift.start_time
            if shift.end_time:
                assignment.end_time = shift.end_time
            session.add(assignment)
            session.flush()
            created += 1
            created_assignments.append(str(assignment.id))
        except Exception as exc:
            errors.append({"row": row["row"], "type": "assignments", "error": str(exc)})

```

Then update `import_session.created_links`:

```python
    import_session.created_links = {
        "soldiers": created_soldiers,
        "duty_shifts": created_duty_shifts,
        "assignments": created_assignments,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_import_sessions_service.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/import_sessions.py backend/app/services/tests/test_import_sessions_service.py
git commit -m "feat: create DutyAssignment rows when confirming an import session"
```

---

### Task 7: Session summary row count + API integration test

**Files:**
- Modify: `backend/app/routes/import_sessions.py` (`_session_summary`)
- Modify: `backend/tests/integration/test_import_sessions_api.py`

**Interfaces:**
- Produces: `GET /import/sessions` list items' `row_summary` dict gains an `"assignments"` count key.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_import_sessions_api.py`:

```python
def _wb_with_assignments(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("assignments")
    ws.append([
        "personal_number", "full_name", "duty_type_name", "duty_location_name",
        "start_date", "end_date", "start_time", "end_time", "is_reserve", "notes",
    ])
    for r in rows:
        ws.append(r)
    return wb


def test_upload_and_confirm_assignments_end_to_end(client, admin_session):
    from app.db.models import DutyAssignment

    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    soldier = create_soldier(admin_session, personal_number=f"sol_{_uid()}")
    admin_session.commit()
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")

    wb = _wb_with_assignments([
        [soldier.personal_number, soldier.full_name, dt.name, loc.name,
         "15.06.2024", "16.06.2024", "", "", "false", ""],
    ])
    # No matching shift exists yet, so this row will resolve as an error —
    # this test only verifies the end-to-end wiring (upload -> list -> get -> confirm),
    # not the resolution rules (covered in test_import_sessions_service.py).
    resp = _upload(client, _token(admin), _to_bytes(wb))
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]
    assert resp.json()["preview"]["assignments"][0]["action"] == "error"

    list_resp = client.get(
        "/api/import/sessions", headers={"Authorization": f"Bearer {_token(admin)}"}
    )
    summary = next(s for s in list_resp.json() if s["id"] == session_id)
    assert summary["row_summary"]["assignments"] == 1

    detail_resp = client.get(
        f"/api/import/sessions/{session_id}", headers={"Authorization": f"Bearer {_token(admin)}"}
    )
    assert detail_resp.json()["parsed_state"]["assignments"][0]["action"] == "error"

    confirm_resp = client.post(
        f"/api/import/sessions/{session_id}/confirm",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["created"] == 0  # error row, nothing created
    assert admin_session.execute(select(DutyAssignment)).scalars().all() == []
```

Add `from sqlalchemy import select` to the test file's imports if not already present (it is not currently imported there — check the top of the file first).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_import_sessions_api.py::test_upload_and_confirm_assignments_end_to_end -v`
Expected: FAIL — `summary["row_summary"]` has no `"assignments"` key (KeyError via `next(...)` succeeding but the assertion failing with `KeyError`).

- [ ] **Step 3: Add the count to `_session_summary`**

Edit `backend/app/routes/import_sessions.py`, in `_session_summary` (lines 35-46):

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
            "assignments": len(state.get("assignments", [])),
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_import_sessions_api.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/import_sessions.py backend/tests/integration/test_import_sessions_api.py
git commit -m "feat: include assignments count in import session summary"
```

---

### Task 8: Export endpoint — `GET /import/export`

**Files:**
- Modify: `backend/app/routes/import_excel.py`
- Create: `backend/tests/integration/test_import_export.py`
- Modify: `frontend/src/pages/ImportUploadPage.tsx`

**Interfaces:**
- Produces: `GET /api/import/export` — returns an xlsx (3 sheets: `soldiers`, `duty_shifts`, `assignments`) reflecting current DB state, same column layout as the template.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_import_export.py`:

```python
from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

import openpyxl
import pytest

from app.db.models import DutyAssignment, DutyLocation, DutyShift, DutyShiftNodeQuota
from app.services.duty_config import create_duty_type
from tests.helpers import auth_headers, create_node, create_soldier


def _uid() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


def test_export_round_trips_soldiers_duty_shifts_and_assignments(client, admin_session):
    node = create_node(admin_session, level="branch", name=f"node_{_uid()}")
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    soldier = create_soldier(admin_session, personal_number=f"sol_{_uid()}", hierarchy_node_id=node.id)
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2024, 6, 15), end_date=date(2024, 6, 16),
        required_count=2,
    )
    admin_session.add(shift)
    admin_session.flush()
    admin_session.add(DutyShiftNodeQuota(duty_shift_id=shift.id, hierarchy_node_id=node.id, count=1))
    admin_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        duty_shift_id=shift.id, start_date=shift.start_date, end_date=shift.end_date,
    ))
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    admin_session.commit()

    token = auth_headers(admin)["Authorization"].split(" ", 1)[1]
    resp = client.get("/api/import/export", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert "spreadsheetml" in resp.headers["content-type"]

    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert set(wb.sheetnames) == {"soldiers", "duty_shifts", "assignments"}

    soldier_rows = list(wb["soldiers"].iter_rows(min_row=2, values_only=True))
    assert any(r[0] == soldier.personal_number for r in soldier_rows)

    shift_rows = list(wb["duty_shifts"].iter_rows(min_row=2, values_only=True))
    matching_shift = next(r for r in shift_rows if r[0] == dt.name and r[1] == loc.name)
    assert matching_shift[6] == 2  # required_count
    assert node.name in matching_shift[7]  # node_quotas string

    assignment_rows = list(wb["assignments"].iter_rows(min_row=2, values_only=True))
    assert len(assignment_rows) == 1
    a = assignment_rows[0]
    assert a[0] == soldier.personal_number
    assert a[1] == soldier.full_name
    assert a[2] == dt.name
    assert a[3] == loc.name


def test_export_omits_assignments_without_linked_shift(client, admin_session):
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    soldier = create_soldier(admin_session, personal_number=f"sol_{_uid()}")
    admin_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2024, 6, 15), end_date=date(2024, 6, 16),
    ))  # no duty_shift_id
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    admin_session.commit()

    token = auth_headers(admin)["Authorization"].split(" ", 1)[1]
    resp = client.get("/api/import/export", headers={"Authorization": f"Bearer {token}"})
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assignment_rows = list(wb["assignments"].iter_rows(min_row=2, values_only=True))
    assert not any(r[0] == soldier.personal_number for r in assignment_rows)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_import_export.py -v`
Expected: FAIL — 404 (no `/import/export` route yet).

- [ ] **Step 3: Implement the export endpoint**

Edit `backend/app/routes/import_excel.py`. Add `DutyShift` and `DutyShiftNodeQuota` to the model imports:

```python
from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyShift,
    DutyShiftNodeQuota,
    DutyType,
    HierarchyNode,
    Soldier,
)
```

Add the endpoint at the end of the file, after `download_template`:

```python
# ── Export current data ─────────────────────────────────────────────────────────

@router.get("/export")
def export_current_data(
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    """Dump current soldiers/duty_shifts/assignments into the same 3-sheet
    layout as the import template, for a full export -> edit -> re-import
    round trip. Assignments with no linked `duty_shift_id` (not tied to a
    shift instance) are omitted — they have no composite key to export."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    nodes_by_id = {n.id: n for n in session.execute(select(HierarchyNode)).scalars()}
    duty_types_by_id = {dt.id: dt for dt in session.execute(select(DutyType)).scalars()}
    locations_by_id = {loc.id: loc for loc in session.execute(select(DutyLocation)).scalars()}

    ws_s = wb.create_sheet("soldiers")
    ws_s.append(["personal_number", "full_name", "rank", "gender", "is_officer",
                  "hierarchy_node_name", "enrolled_at", "enlistment_date", "phone", "email"])
    for s in session.execute(select(Soldier)).scalars():
        node = nodes_by_id.get(s.hierarchy_node_id) if s.hierarchy_node_id else None
        ws_s.append([
            s.personal_number, s.full_name, s.rank, s.gender,
            "" if s.is_officer is None else ("true" if s.is_officer else "false"),
            node.name if node else "",
            s.enrolled_at.strftime("%d.%m.%Y") if s.enrolled_at else "",
            s.enlistment_date.strftime("%d.%m.%Y") if s.enlistment_date else "",
            s.phone or "", s.email or "",
        ])

    quotas_by_shift: dict[uuid.UUID, list[str]] = {}
    for quota, node_name in session.execute(
        select(DutyShiftNodeQuota, HierarchyNode.name).join(
            HierarchyNode, DutyShiftNodeQuota.hierarchy_node_id == HierarchyNode.id
        )
    ):
        quotas_by_shift.setdefault(quota.duty_shift_id, []).append(f"{node_name}:{quota.count}")

    shifts = session.execute(select(DutyShift)).scalars().all()
    ws_d = wb.create_sheet("duty_shifts")
    ws_d.append(["duty_type_name", "duty_location_name", "start_date", "end_date",
                  "start_time", "end_time", "required_count", "node_quotas", "notes"])
    for shift in shifts:
        dt = duty_types_by_id.get(shift.duty_type_id)
        loc = locations_by_id.get(shift.duty_location_id)
        ws_d.append([
            dt.name if dt else "", loc.name if loc else "",
            shift.start_date.strftime("%d.%m.%Y"), shift.end_date.strftime("%d.%m.%Y"),
            shift.start_time, shift.end_time, shift.required_count,
            ";".join(quotas_by_shift.get(shift.id, [])), shift.notes or "",
        ])

    shifts_by_id = {shift.id: shift for shift in shifts}
    soldiers_by_id = {s.id: s for s in session.execute(select(Soldier)).scalars()}
    ws_a = wb.create_sheet("assignments")
    ws_a.append(["personal_number", "full_name", "duty_type_name", "duty_location_name",
                  "start_date", "end_date", "start_time", "end_time", "is_reserve", "notes"])
    for a in session.execute(select(DutyAssignment)).scalars():
        if a.duty_shift_id is None:
            continue
        shift = shifts_by_id.get(a.duty_shift_id)
        if shift is None:
            continue
        soldier = soldiers_by_id.get(a.soldier_id)
        dt = duty_types_by_id.get(shift.duty_type_id)
        loc = locations_by_id.get(shift.duty_location_id)
        ws_a.append([
            soldier.personal_number if soldier else "",
            soldier.full_name if soldier else "",
            dt.name if dt else "", loc.name if loc else "",
            shift.start_date.strftime("%d.%m.%Y"), shift.end_date.strftime("%d.%m.%Y"),
            shift.start_time, shift.end_time,
            "true" if a.is_reserve else "false",
            a.notes or "",
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="export.xlsx"'},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_import_export.py -v`
Expected: all PASS.

- [ ] **Step 5: Add a download link on the upload page**

Edit `frontend/src/pages/ImportUploadPage.tsx`, right after the "הורד תבנית לדוגמה" link (after line 51):

```tsx
          <a
            href="/api/import/template"
            className="text-indigo-600 hover:underline text-sm"
          >
            הורד תבנית לדוגמה ›
          </a>
          <a
            href="/api/import/export"
            className="text-indigo-600 hover:underline text-sm"
          >
            ייצוא המצב הנוכחי ›
          </a>
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/import_excel.py backend/tests/integration/test_import_export.py frontend/src/pages/ImportUploadPage.tsx
git commit -m "feat: add GET /import/export endpoint for full DB state round trip"
```

---

### Task 9: Frontend types

**Files:**
- Modify: `frontend/src/api/importSessions.ts`

**Interfaces:**
- Produces: `AssignmentRow` interface; `RowBase.warnings?: string[]`; `ParsedState.assignments: AssignmentRow[]`; `SessionSummary.row_summary.assignments: number`.

- [ ] **Step 1: Update `importSessions.ts`**

Edit `frontend/src/api/importSessions.ts`:

Change `RowBase` (lines 19-23):

```ts
export interface RowBase {
  row: number;
  action: "new" | "update" | "error" | "out_of_scope" | "skip";
  errors: string[];
  warnings?: string[];
}
```

Add a new interface after `ShiftTemplateRow` (after line 68):

```ts
export interface AssignmentRow extends RowBase {
  personal_number: string;
  full_name: string;
  duty_type_name: string;
  duty_location_name: string;
  start_date: string;
  end_date: string;
  start_time: string | null;
  end_time: string | null;
  is_reserve: boolean;
  notes: string | null;
  resolved_soldier_id: string | null;
  resolved_duty_shift_id: string | null;
  matched_session_row: number | null;
}
```

Change `ParsedState` (lines 70-76):

```ts
export interface ParsedState {
  soldiers: SoldierRow[];
  duty_shifts: DutyShiftRow[];
  shift_templates: ShiftTemplateRow[];
  assignments: AssignmentRow[];
  parser_id: string;
  parser_warnings: string[];
}
```

Change `SessionSummary.row_summary` (lines 82-86):

```ts
  row_summary: {
    soldiers: number;
    duty_shifts: number;
    assignments: number;
  };
```

- [ ] **Step 2: Run the frontend typecheck**

Run: `cd frontend && npm run typecheck`
Expected: fails at this point (`ImportSessionReviewPage.tsx` destructures `detail.parsed_state` without `assignments` — TypeScript won't error on that by itself since it's structural, but `frontend/src/pages/ImportSessionReviewPage.tsx`'s `TabKey` union and tab list will be checked in Task 10). If it passes cleanly already, that's fine too — proceed to Task 10 either way.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/importSessions.ts
git commit -m "feat: add AssignmentRow and warnings types for import sessions"
```

---

### Task 10: Frontend UI — assignments tab

**Files:**
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`

**Interfaces:**
- Consumes: `AssignmentRow`, `ParsedState.assignments` (Task 9).

- [ ] **Step 1: Update imports and `TabKey`**

Edit `frontend/src/pages/ImportSessionReviewPage.tsx`. Add `AssignmentRow` to the import from `../api/importSessions` (line 8-20):

```tsx
import {
  type SessionDetail,
  type ConfirmSessionResult,
  type RowBase,
  type Selections,
  type ShiftTemplateRow,
  type AssignmentRow,
  getSession,
  reparseSession,
  saveSelections,
  confirmSession,
  listDutyTypesForImport,
  listNodesForImport,
} from "../api/importSessions";
```

Change `TabKey` (line 40):

```tsx
type TabKey = "soldiers" | "duty_shifts" | "shift_templates" | "assignments";
```

- [ ] **Step 2: Extend `StatusChip` to render warnings**

Replace `StatusChip` (lines 47-64):

```tsx
function StatusChip({
  action,
  errors,
  warnings,
}: {
  action: ActionValue;
  errors?: string[];
  warnings?: string[];
}) {
  return (
    <div className="space-y-0.5">
      <span
        className={`px-1.5 py-0.5 rounded text-xs font-medium ${ACTION_CHIP[action]}`}
      >
        {ACTION_LABEL[action]}
      </span>
      {errors && errors.length > 0 && (
        <ul className="text-red-600 text-xs list-none">
          {errors.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      )}
      {warnings && warnings.length > 0 && (
        <ul className="text-yellow-600 text-xs list-none">
          {warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Widen `group` params to include `"assignments"`**

Change `setRowAction` (line 220):

```tsx
  function setRowAction(
    group: "soldiers" | "duty_shifts" | "shift_templates" | "assignments",
    row: number,
    value: string,
  ) {
```

Change `currentSelection` (line 330):

```tsx
  function currentSelection(
    group: "soldiers" | "duty_shifts" | "shift_templates" | "assignments",
    row: RowBase,
  ): string {
```

- [ ] **Step 4: Destructure `assignments`, add the tab button, pass `warnings` to existing `StatusChip` usages**

Change line 349:

```tsx
  const { soldiers, duty_shifts, shift_templates, assignments } = detail.parsed_state;
```

Change the tabs array (lines 362-382) to include the new tab:

```tsx
        <div className="flex gap-2 border-b dark:border-gray-700">
          {(
            [
              ["soldiers", `חיילים (${soldiers.length})`],
              ["duty_shifts", `משמרות (${duty_shifts.length})`],
              ["shift_templates", `תבניות (${shift_templates.length})`],
              ["assignments", `שיבוצים (${assignments.length})`],
            ] as [TabKey, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              className={`px-3 py-2 text-sm font-medium ${
                tab === key
                  ? "border-b-2 border-indigo-600 text-indigo-600"
                  : "text-gray-500"
              }`}
              onClick={() => setTab(key)}
            >
              {label}
            </button>
          ))}
        </div>
```

In the `soldiers` tab body, update the `StatusChip` call (around line 458) to pass warnings:

```tsx
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} warnings={row.warnings} />
                      </td>
```

- [ ] **Step 5: Add the assignments tab table**

Add a new tab block right after the `shift_templates` tab block closes (after line 753, before `{confirmError && (`):

```tsx
        {tab === "assignments" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">שם</th>
                  <th className="text-right p-3">מ&quot;א</th>
                  <th className="text-right p-3">סוג תורנות</th>
                  <th className="text-right p-3">מיקום</th>
                  <th className="text-right p-3">תאריכים</th>
                  <th className="text-right p-3">רזרבה</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {assignments.map((row: AssignmentRow) => {
                  const canToggle =
                    row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">{row.full_name}</td>
                      <td className="p-3">{row.personal_number}</td>
                      <td className="p-3">{row.duty_type_name}</td>
                      <td className="p-3">{row.duty_location_name}</td>
                      <td className="p-3">
                        {row.start_date} – {row.end_date}
                      </td>
                      <td className="p-3">{row.is_reserve ? "כן" : "לא"}</td>
                      <td className="p-3">
                        <StatusChip action={row.action} errors={row.errors} warnings={row.warnings} />
                      </td>
                      {!readOnly && (
                        <td className="p-3">
                          {canToggle && (
                            <select
                              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                              value={currentSelection("assignments", row)}
                              onChange={(e) =>
                                setRowAction("assignments", row.row, e.target.value)
                              }
                            >
                              <option value={row.action}>אישור</option>
                              {row.action !== "skip" && (
                                <option value="skip">דלג</option>
                              )}
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

- [ ] **Step 6: Typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: both pass with zero errors/warnings.

- [ ] **Step 7: Manual verification in the browser**

Start the dev stack (`.\dev.ps1` from repo root if not already running). Log in as an admin/duty_manager user, go to the import upload page, download the template (confirm it now has 3 sheets including `assignments` with sample rows), and upload it as-is. On the review page, confirm a new "שיבוצים" tab appears showing the sample assignment rows (they'll show `action="error"` since the sample `duty_type_name`/`duty_location_name` combo doesn't yet exist as a matching shift in a fresh DB — that's expected; the goal is to confirm the tab renders, not that the sample data is a valid combination).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/ImportSessionReviewPage.tsx
git commit -m "feat: add assignments tab to import session review page"
```

---

## Self-Review Notes

- **Spec coverage:** Template (§1, Task 3), parser (§2, Task 2), soldier fallback + assignment resolution (§3, Tasks 4-5), review UI (§4, Task 10), confirm (§5, Task 6), export (§6, Task 8), tests (§7, throughout). All spec sections have a corresponding task.
- **Shift-matching priority correction:** the spec was corrected (before this plan was written) to check existing DB shifts before session-created shifts, so that re-importing a previous export correctly lands on the duplicate-skip path (Task 5, `_resolve_assignments`, `existing_match` checked before `session_match`).
- **Type consistency:** `matched_session_row` (int | None) and `resolved_duty_shift_id` (str | None) are used consistently across Task 5 (produced), Task 6 (consumed in `confirm_session`), Task 9 (frontend type), and Task 10 (unused directly in UI, but present on `AssignmentRow` for completeness/debugging).
- **No placeholders:** every step has literal, complete code — no "add appropriate handling" phrasing.
