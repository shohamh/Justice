# Import Review Editing, Shift Templates, and Export Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconcile the two disconnected export endpoints into one round-trip-capable Export page, make every duty_types/exemption_types field visible and editable before confirming an import session, and build shift_templates into a first-class importable/exportable/editable sheet.

**Architecture:** Extends the existing session-based import pipeline (`import_sessions.py` service + `ImportSessionReviewPage.tsx`) with a new `_field_overrides` selections namespace (sibling to the existing `_name_mappings`) that lets a user edit a parsed row's fields pre-confirm; `_resolve_and_score()` applies overrides before each resolver's existing validation runs, so edited values get re-validated for free and `confirm_session()` needs no changes. Shift templates get a full parser→resolver→confirm pipeline mirroring the existing `duty_types`/`duty_locations` sheets, replacing dead scaffolding that never wired up.

**Tech Stack:** Python/FastAPI/SQLAlchemy backend, openpyxl for xlsx, React/TypeScript frontend, pytest, vitest.

## Global Constraints

- Date format in all sheets: `dd.mm.yyyy` (parsed via `app/services/import_parsers/_shared_parsing.py::parse_date`).
- Boolean format: `"true"/"false"` (and Hebrew `"כן"/"נכון"`), parsed via `_shared_parsing.py::parse_bool`.
- Time format: `HH:MM` strings.
- All new user-facing strings (errors/warnings/UI labels) are in Hebrew, matching the existing codebase convention.
- Backend tests: `pytest -m duty -q` or targeted `pytest <path> -q` (per CLAUDE.md, don't run the full suite mid-task).
- Frontend: `npm run lint` and `npm test` from `frontend/`, run before finishing.
- Import only ever creates/updates; it never deletes an entity absent from a sheet (existing rule across all sheets, unchanged here).

---

### Task 1: Export reconciliation — `/planning/export` gains a data-sheets checkbox

**Files:**
- Modify: `frontend/src/pages/planning/ExportPage.tsx`
- Test: `frontend/src/pages/planning/ExportPage.test.tsx`

**Interfaces:**
- Consumes: existing `GET /api/import/export` endpoint (returns an xlsx with `soldiers`, `duty_shifts`, `assignments` sheets today — `shift_templates` added to it in Task 12, no frontend change needed when that lands).
- Produces: no new exports; `handleExport()`'s merged workbook now optionally includes the import/export sheets.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/pages/planning/ExportPage.test.tsx` (check the file's existing mocking setup for `fetch`/`getAccessToken` first — follow its established pattern for mocking `/api/config/export`, and mirror it for `/api/import/export`):

```tsx
it("merges /api/import/export sheets when the data checkbox is checked", async () => {
  const importWb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(importWb, XLSX.utils.aoa_to_sheet([["personal_number"], ["123"]]), "soldiers");
  const importBuf = XLSX.write(importWb, { type: "array", bookType: "xlsx" });

  const fetchMock = vi.fn().mockResolvedValue({
    arrayBuffer: () => Promise.resolve(importBuf),
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<ExportPage />);
  fireEvent.click(await screen.findByLabelText(/נתוני מערכת/));
  fireEvent.click(screen.getByText("ייצוא"));

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/import/export",
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm test -- ExportPage -t "merges /api/import/export"`
Expected: FAIL — no checkbox labeled "נתוני מערכת" exists yet.

- [ ] **Step 3: Add the checkbox and merge logic**

In `frontend/src/pages/planning/ExportPage.tsx`, add a new checkbox alongside the existing `transparency`/`sub_units`/config checkboxes:

```tsx
<label className="flex items-center gap-2">
  <input
    type="checkbox"
    checked={!!checked.system_data}
    onChange={() => toggle("system_data")}
  />
  ייצוא נתוני מערכת (חיילים, משמרות, שיבוצים, תבניות)
</label>
```

Place it right after the `CONFIG_SHEET_OPTIONS.map(...)` block, before the export button.

In `handleExport()`, after the existing `configSheets` block and before `if (wb.SheetNames.length > 0)`:

```tsx
if (checked.system_data) {
  const resp = await fetch("/api/import/export", {
    headers: { Authorization: `Bearer ${getAccessToken() ?? ""}` },
  });
  const buf = await resp.arrayBuffer();
  const dataWb = XLSX.read(buf, { type: "array" });
  for (const name of dataWb.SheetNames) {
    XLSX.utils.book_append_sheet(wb, dataWb.Sheets[name], name);
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- ExportPage -t "merges /api/import/export"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/planning/ExportPage.tsx frontend/src/pages/planning/ExportPage.test.tsx
git commit -m "feat: reconcile export page with the full data round-trip export"
```

---

### Task 2: Backend — generic field-override mechanism for duty_types and exemption_types

**Files:**
- Modify: `backend/app/services/import_sessions.py` (`_resolve_duty_types`, `_resolve_exemption_types`, `_resolve_and_score`)
- Test: `backend/app/services/tests/test_import_sessions_service.py`

**Interfaces:**
- Consumes: `selections["_field_overrides"]["duty_types"][str(row)]: dict`, `selections["_field_overrides"]["exemption_types"][str(row)]: dict` (new selections shape, plain dicts of field-name → new value).
- Produces: `_resolve_duty_types(session, data, node_by_name=None, node_by_row=None, overrides=None)` and `_resolve_exemption_types(session, data, dt_by_name=None, dt_by_row=None, overrides=None)` — same return shape as today, values reflect any override applied.

- [ ] **Step 1: Write the failing tests**

Add to `backend/app/services/tests/test_import_sessions_service.py`:

```python
def _wb_with_duty_types(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("duty_types")
    ws.append([
        "name", "score_per_day", "description", "active", "reserve_ratio", "reserve_minimum",
        "is_external", "contact_name", "contact_phone", "start_time", "end_time",
        "instructions", "eligible_units", "requirements_json",
    ])
    for r in rows:
        ws.append(r)
    return wb


def _wb_with_exemption_types(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("exemption_types")
    ws.append([
        "name", "description", "is_global", "is_medical", "is_commander_exemption",
        "applies_to_duty_types",
    ])
    for r in rows:
        ws.append(r)
    return wb


def test_duty_type_field_override_changes_resolved_score(admin_session):
    wb = _wb_with_duty_types([
        ["שמירה", "1.00", "", "true", "", "", "false", "", "", "", "", "", "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row_num = sess.parsed_state["duty_types"][0]["row"]

    set_selections(admin_session, session_id=sess.id, selections={
        "_field_overrides": {"duty_types": {str(row_num): {"score_per_day": "2.50"}}},
    })
    admin_session.commit()

    reparse_session(admin_session, session_id=sess.id, actor=admin)
    row = sess.parsed_state["duty_types"][0]
    assert row["score_per_day"] == "2.50"


def test_duty_type_field_override_invalid_value_produces_row_error(admin_session):
    wb = _wb_with_duty_types([
        ["שמירה", "1.00", "", "true", "", "", "false", "", "", "", "", "", "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row_num = sess.parsed_state["duty_types"][0]["row"]

    set_selections(admin_session, session_id=sess.id, selections={
        "_field_overrides": {"duty_types": {str(row_num): {"score_per_day": "not-a-number"}}},
    })
    admin_session.commit()

    reparse_session(admin_session, session_id=sess.id, actor=admin)
    row = sess.parsed_state["duty_types"][0]
    assert row["action"] == "error"
    assert any("ניקוד ליום לא תקין" in e for e in row["errors"])


def test_exemption_type_field_override_changes_resolved_flag(admin_session):
    wb = _wb_with_exemption_types([
        ["פטור", "", "false", "false", "false", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row_num = sess.parsed_state["exemption_types"][0]["row"]

    set_selections(admin_session, session_id=sess.id, selections={
        "_field_overrides": {"exemption_types": {str(row_num): {"is_medical": True}}},
    })
    admin_session.commit()

    reparse_session(admin_session, session_id=sess.id, actor=admin)
    row = sess.parsed_state["exemption_types"][0]
    assert row["is_medical"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_import_sessions_service.py -v -k "field_override"`
Expected: FAIL — `_resolve_duty_types`/`_resolve_exemption_types` don't accept overrides yet; edited values are ignored.

- [ ] **Step 3: Implement overrides in `_resolve_duty_types`**

In `backend/app/services/import_sessions.py`, change the signature and body of `_resolve_duty_types` (currently at line 292). Replace:

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
        if row.reserve_ratio is not None and row.reserve_ratio != "":
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
                try:
                    node = session.get(HierarchyNode, uuid.UUID(mapped_id))
                except ValueError:
                    pass
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

with:

```python
def _resolve_duty_types(
    session: Session,
    data: ParsedImportData,
    node_by_name: dict[str, str] | None = None,
    node_by_row: dict[str, str] | None = None,
    overrides: dict[str, dict] | None = None,
) -> list[dict]:
    node_by_name = node_by_name or {}
    node_by_row = node_by_row or {}
    overrides = overrides or {}
    existing_by_name = {dt.name: dt for dt in session.execute(select(DutyType)).scalars()}
    nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}

    out = []
    for row in data.duty_types:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        name = field("name", row.name)
        raw_score = field("score_per_day", row.score_per_day)
        raw_reserve_ratio = field("reserve_ratio", row.reserve_ratio)
        raw_requirements_json = field("requirements_json", row.requirements_json)
        eligible_unit_names = field("eligible_unit_names", row.eligible_unit_names)

        score_per_day: Decimal | None = None
        try:
            score_per_day = Decimal(raw_score) if raw_score else None
            if score_per_day is None:
                errors.append("חסר ניקוד ליום")
        except Exception:
            errors.append(f"ניקוד ליום לא תקין '{raw_score}'")

        reserve_ratio: Decimal | None = None
        if raw_reserve_ratio is not None and raw_reserve_ratio != "":
            try:
                reserve_ratio = Decimal(raw_reserve_ratio)
            except Exception:
                errors.append(f"יחס רזרבה לא תקין '{raw_reserve_ratio}'")

        requirements: dict | None = field("requirements", None)
        if requirements is None and raw_requirements_json:
            try:
                requirements = json.loads(raw_requirements_json)
            except Exception as exc:
                errors.append(f"JSON לא תקין בעמודת requirements_json: {exc}")

        resolved_eligible_node_ids: list[str] = field("resolved_eligible_node_ids", None) or []
        if "resolved_eligible_node_ids" not in override:
            resolved_eligible_node_ids = []
            for unit_name in eligible_unit_names:
                row_key = f"duty_types:{row.source_row}:{unit_name}"
                mapped_id = node_by_row.get(row_key) or node_by_name.get(unit_name)
                node = None
                if mapped_id:
                    try:
                        node = session.get(HierarchyNode, uuid.UUID(mapped_id))
                    except ValueError:
                        pass
                if node is None:
                    node = nodes_by_name.get(unit_name)
                if node is None:
                    errors.append(f"יחידה זכאית לא מזוהה '{unit_name}'")
                else:
                    resolved_eligible_node_ids.append(str(node.id))

        existing = existing_by_name.get(name) if name else None
        action = "error" if errors else ("update" if existing else "new")

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "name": name,
            "score_per_day": str(score_per_day) if score_per_day is not None else None,
            "description": field("description", row.description),
            "active": field("active", row.active),
            "reserve_ratio": str(reserve_ratio) if reserve_ratio is not None else None,
            "reserve_minimum": field("reserve_minimum", row.reserve_minimum),
            "is_external": field("is_external", row.is_external),
            "contact_name": field("contact_name", row.contact_name),
            "contact_phone": field("contact_phone", row.contact_phone),
            "start_time": field("start_time", row.start_time),
            "end_time": field("end_time", row.end_time),
            "instructions": field("instructions", row.instructions),
            "resolved_eligible_node_ids": resolved_eligible_node_ids,
            "requirements": requirements,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out
```

Note: an override can supply `resolved_eligible_node_ids` directly (bypassing name resolution — this is how the frontend's `SubHierarchySelector`-based modal from Task 7 writes its edit, since it picks nodes by id already) or `eligible_unit_names` (re-triggers name resolution, for symmetry, though the UI won't use this path). Same reasoning applies to `requirements` (direct object override, from the modal) vs `requirements_json` (re-parsed).

- [ ] **Step 4: Implement overrides in `_resolve_exemption_types`**

Replace the body of `_resolve_exemption_types` (currently at line 372) analogously:

```python
def _resolve_exemption_types(
    session: Session,
    data: ParsedImportData,
    dt_by_name: dict[str, str] | None = None,
    dt_by_row: dict[str, str] | None = None,
    overrides: dict[str, dict] | None = None,
) -> list[dict]:
    """Resolve exemption types from import data.

    Matches by name (unique constraint on exemption_types.name).
    Resolves applies_to_duty_type_names to duty type IDs from both DB and import sheet.
    """
    dt_by_name = dt_by_name or {}
    dt_by_row = dt_by_row or {}
    overrides = overrides or {}
    existing_by_name = {et.name: et for et in session.execute(select(ExemptionType)).scalars()}
    duty_types_by_name = {dt.name: dt for dt in session.execute(select(DutyType)).scalars()}

    out = []
    for row in data.exemption_types:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        name = field("name", row.name)
        applies_to_duty_type_names = field("applies_to_duty_type_names", row.applies_to_duty_type_names)

        resolved_duty_type_ids: list[str] | None = field("resolved_duty_type_ids", None)
        if resolved_duty_type_ids is None:
            resolved_duty_type_ids = []
            for duty_type_name in applies_to_duty_type_names:
                row_key = f"exemption_types:{row.source_row}:{duty_type_name}"
                mapped_id = dt_by_row.get(row_key) or dt_by_name.get(duty_type_name)
                duty_type = None
                if mapped_id:
                    try:
                        duty_type = session.get(DutyType, uuid.UUID(mapped_id))
                    except ValueError:
                        pass
                if duty_type is None:
                    duty_type = duty_types_by_name.get(duty_type_name)
                if duty_type is None:
                    errors.append(f"סוג חובה לא מזוהה '{duty_type_name}' (applies_to)")
                else:
                    resolved_duty_type_ids.append(str(duty_type.id))

        is_global_raw = field("is_global", row.is_global)
        is_medical_raw = field("is_medical", row.is_medical)
        is_commander_exemption_raw = field("is_commander_exemption", row.is_commander_exemption)
        is_global = is_global_raw if is_global_raw is not None else False
        is_medical = is_medical_raw if is_medical_raw is not None else False
        is_commander_exemption = is_commander_exemption_raw if is_commander_exemption_raw is not None else False

        existing = existing_by_name.get(name) if name else None
        action = "error" if errors else ("update" if existing else "new")

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "name": name,
            "description": field("description", row.description),
            "is_global": is_global,
            "is_medical": is_medical,
            "is_commander_exemption": is_commander_exemption,
            "resolved_duty_type_ids": resolved_duty_type_ids,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out
```

- [ ] **Step 5: Wire overrides through `_resolve_and_score`**

Modify `_resolve_and_score` (currently at line 734):

```python
def _resolve_and_score(
    session: Session,
    data: ParsedImportData,
    actor: Soldier,
    selections: dict | None = None,
) -> dict:
    nm = (selections or {}).get("_name_mappings", {})
    fo = (selections or {}).get("_field_overrides", {})
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
        "duty_locations": _resolve_duty_locations(session, data),
        "hierarchy": _resolve_hierarchy(session, data, actor, node_by_name, node_by_row),
        "duty_types": _resolve_duty_types(session, data, node_by_name, node_by_row, fo.get("duty_types", {})),
        "exemption_types": _resolve_exemption_types(session, data, dt_by_name, dt_by_row, fo.get("exemption_types", {})),
        "parser_id": data.parser_id,
        "parser_warnings": data.parser_warnings,
    }
```

(Only the two changed call sites and the new `fo = ...` line — everything else in this function is unchanged; verify the exact current body first with `grep -n "_resolve_and_score" -A 20 backend/app/services/import_sessions.py` since field order may differ slightly from this listing.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_import_sessions_service.py -v -k "field_override"`
Expected: all 3 PASS.

- [ ] **Step 7: Run the full duty_types/exemption_types test subset to check nothing broke**

Run: `cd backend && pytest app/services/tests/test_import_sessions_service.py -v -k "duty_type or exemption_type"`
Expected: all PASS (pre-existing tests for these resolvers unaffected since `overrides` defaults to `{}`).

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/import_sessions.py backend/app/services/tests/test_import_sessions_service.py
git commit -m "feat: support pre-confirm field overrides for duty_types and exemption_types rows"
```

---

### Task 3: Frontend — full-detail duty_types tab (read-only fields, no edit yet)

**Files:**
- Modify: `frontend/src/api/importSessions.ts`
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`
- Modify: `frontend/src/pages/ImportSessionReviewPage.test.tsx`

**Interfaces:**
- Produces: `DutyTypeImportRow` gains `description`, `active`, `reserve_ratio`, `reserve_minimum`, `is_external`, `contact_name`, `contact_phone`, `start_time`, `end_time`, `instructions` (all already returned by the backend from Task 2 — no backend change here).

- [ ] **Step 1: Extend the TS interface**

In `frontend/src/api/importSessions.ts`, replace:

```ts
export interface DutyTypeImportRow extends RowBase {
  name: string;
  score_per_day: string | null;
  resolved_eligible_node_ids: string[];
  requirements: Record<string, unknown> | null;
  existing_id: string | null;
}
```

with:

```ts
export interface DutyTypeImportRow extends RowBase {
  name: string;
  score_per_day: string | null;
  description: string | null;
  active: boolean | null;
  reserve_ratio: string | null;
  reserve_minimum: number | null;
  is_external: boolean | null;
  contact_name: string | null;
  contact_phone: string | null;
  start_time: string | null;
  end_time: string | null;
  instructions: string | null;
  resolved_eligible_node_ids: string[];
  requirements: Record<string, unknown> | null;
  existing_id: string | null;
}
```

- [ ] **Step 2: Update the existing test fixture to match the extended shape**

In `frontend/src/pages/ImportSessionReviewPage.test.tsx`, find the `"renders the duty_types tab and exemption_types tab"` test (around line 411) and replace its `detail.parsed_state.duty_types` fixture:

```tsx
detail.parsed_state.duty_types = [
  {
    row: 2,
    action: "new",
    errors: [],
    name: "שמירה",
    score_per_day: "1.50",
    description: "שמירה בשער",
    active: true,
    reserve_ratio: "0.200",
    reserve_minimum: 2,
    is_external: false,
    contact_name: "דני",
    contact_phone: "050-1234567",
    start_time: "20:00",
    end_time: "06:00",
    instructions: "הצטיידות במקלע",
    resolved_eligible_node_ids: [],
    requirements: null,
    existing_id: null,
  },
];
```

- [ ] **Step 3: Write the failing test for full-detail rendering**

Add a new test in the same file, right after the existing `"renders the duty_types tab and exemption_types tab"` test:

```tsx
it("shows full duty_type detail fields", async () => {
  const detail = makeDraftDetail();
  detail.parsed_state.duty_types = [
    {
      row: 2,
      action: "new",
      errors: [],
      name: "שמירה",
      score_per_day: "1.50",
      description: "שמירה בשער",
      active: true,
      reserve_ratio: "0.200",
      reserve_minimum: 2,
      is_external: false,
      contact_name: "דני",
      contact_phone: "050-1234567",
      start_time: "20:00",
      end_time: "06:00",
      instructions: "הצטיידות במקלע",
      resolved_eligible_node_ids: [],
      requirements: null,
      existing_id: null,
    },
  ];
  vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

  renderPage();
  await screen.findByText("יוסי כהן");
  fireEvent.click(screen.getByText("סוגי תורנות (1)"));

  expect(await screen.findByDisplayValue("שמירה בשער")).toBeInTheDocument();
  expect(screen.getByDisplayValue("דני")).toBeInTheDocument();
  expect(screen.getByDisplayValue("050-1234567")).toBeInTheDocument();
  expect(screen.getByDisplayValue("הצטיידות במקלע")).toBeInTheDocument();
});
```

- [ ] **Step 4: Run test to verify it fails**

Run (from `frontend/`): `npm test -- ImportSessionReviewPage -t "shows full duty_type detail fields"`
Expected: FAIL — those fields aren't rendered yet.

- [ ] **Step 5: Replace the duty_types tab table with full-detail columns**

In `frontend/src/pages/ImportSessionReviewPage.tsx`, replace the entire `{tab === "duty_types" && (...)}` block (currently lines 977-1018) with:

```tsx
{tab === "duty_types" && (
  <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
    <table className="w-full text-sm">
      <thead>
        <tr className="text-gray-500 border-b dark:border-gray-700">
          <th className="text-right p-3">שם</th>
          <th className="text-right p-3">ניקוד ליום</th>
          <th className="text-right p-3">תיאור</th>
          <th className="text-right p-3">פעיל</th>
          <th className="text-right p-3">יחס רזרבה</th>
          <th className="text-right p-3">מינימום רזרבה</th>
          <th className="text-right p-3">חיצוני</th>
          <th className="text-right p-3">איש קשר</th>
          <th className="text-right p-3">טלפון</th>
          <th className="text-right p-3">שעת התחלה</th>
          <th className="text-right p-3">שעת סיום</th>
          <th className="text-right p-3">הוראות</th>
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
              <td className="p-3">{row.description ?? "—"}</td>
              <td className="p-3">{row.active === null ? "—" : row.active ? "כן" : "לא"}</td>
              <td className="p-3">{row.reserve_ratio ?? "—"}</td>
              <td className="p-3">{row.reserve_minimum ?? "—"}</td>
              <td className="p-3">{row.is_external === null ? "—" : row.is_external ? "כן" : "לא"}</td>
              <td className="p-3">{row.contact_name ?? "—"}</td>
              <td className="p-3">{row.contact_phone ?? "—"}</td>
              <td className="p-3">{row.start_time ?? "—"}</td>
              <td className="p-3">{row.end_time ?? "—"}</td>
              <td className="p-3">{row.instructions ?? "—"}</td>
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
```

This is a read-only-fields pass (inline `<input>`s land in Task 5) — using `<input>` elements now (not plain text) so Step 3's `findByDisplayValue` assertions pass while keeping the diff to a single follow-up in Task 5 small. Use disabled inputs for this task:

Replace each detail `<td>` (description through instructions) with a disabled `<input>` instead of plain text, e.g.:

```tsx
<td className="p-3"><input className="border rounded p-1 text-sm w-40 dark:bg-gray-700 dark:border-gray-600" value={row.description ?? ""} disabled /></td>
```

Apply the same `<input disabled ... />` wrapping to `description`, `contact_name`, `contact_phone`, `start_time`, `end_time`, and a `<textarea disabled>` for `instructions`. Leave `active`/`is_external` (booleans) and `score_per_day`/`reserve_ratio`/`reserve_minimum` as plain text for now — they become interactive in Task 5.

- [ ] **Step 6: Run test to verify it passes**

Run: `npm test -- ImportSessionReviewPage -t "shows full duty_type detail fields"`
Expected: PASS.

- [ ] **Step 7: Run the full test file to check nothing broke**

Run: `npm test -- ImportSessionReviewPage`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/importSessions.ts frontend/src/pages/ImportSessionReviewPage.tsx frontend/src/pages/ImportSessionReviewPage.test.tsx
git commit -m "feat: show full duty_type field detail in import review table"
```

---

### Task 4: Frontend — full-detail exemption_types tab (read-only fields, no edit yet)

**Files:**
- Modify: `frontend/src/api/importSessions.ts`
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`
- Modify: `frontend/src/pages/ImportSessionReviewPage.test.tsx`

**Interfaces:**
- Produces: `ExemptionTypeImportRow` gains `description`, `is_global`, `is_medical`, `is_commander_exemption` (all already returned by the backend from Task 2).

- [ ] **Step 1: Extend the TS interface**

In `frontend/src/api/importSessions.ts`, replace:

```ts
export interface ExemptionTypeImportRow extends RowBase {
  name: string;
  resolved_duty_type_ids: string[];
  existing_id: string | null;
}
```

with:

```ts
export interface ExemptionTypeImportRow extends RowBase {
  name: string;
  description: string | null;
  is_global: boolean;
  is_medical: boolean;
  is_commander_exemption: boolean;
  resolved_duty_type_ids: string[];
  existing_id: string | null;
}
```

- [ ] **Step 2: Update the existing test fixture**

In `frontend/src/pages/ImportSessionReviewPage.test.tsx`, in the `"renders the duty_types tab and exemption_types tab"` test, replace `detail.parsed_state.exemption_types`:

```tsx
detail.parsed_state.exemption_types = [
  {
    row: 2,
    action: "new",
    errors: [],
    name: "פטור",
    description: "פטור רפואי",
    is_global: false,
    is_medical: true,
    is_commander_exemption: false,
    resolved_duty_type_ids: [],
    existing_id: null,
  },
];
```

- [ ] **Step 3: Write the failing test**

```tsx
it("shows full exemption_type detail fields", async () => {
  const detail = makeDraftDetail();
  detail.parsed_state.exemption_types = [
    {
      row: 2,
      action: "new",
      errors: [],
      name: "פטור",
      description: "פטור רפואי",
      is_global: false,
      is_medical: true,
      is_commander_exemption: false,
      resolved_duty_type_ids: [],
      existing_id: null,
    },
  ];
  vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

  renderPage();
  await screen.findByText("יוסי כהן");
  fireEvent.click(screen.getByText("פטורים (1)"));

  expect(await screen.findByDisplayValue("פטור רפואי")).toBeInTheDocument();
});
```

- [ ] **Step 4: Run test to verify it fails**

Run: `npm test -- ImportSessionReviewPage -t "shows full exemption_type detail fields"`
Expected: FAIL.

- [ ] **Step 5: Replace the exemption_types tab table**

Replace the entire `{tab === "exemption_types" && (...)}` block (currently lines 1020-1059) with:

```tsx
{tab === "exemption_types" && (
  <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
    <table className="w-full text-sm">
      <thead>
        <tr className="text-gray-500 border-b dark:border-gray-700">
          <th className="text-right p-3">שם</th>
          <th className="text-right p-3">תיאור</th>
          <th className="text-right p-3">גלובלי</th>
          <th className="text-right p-3">רפואי</th>
          <th className="text-right p-3">פטור פיקודי</th>
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
                <input
                  className="border rounded p-1 text-sm w-40 dark:bg-gray-700 dark:border-gray-600"
                  value={row.description ?? ""}
                  disabled
                />
              </td>
              <td className="p-3">{row.is_global ? "כן" : "לא"}</td>
              <td className="p-3">{row.is_medical ? "כן" : "לא"}</td>
              <td className="p-3">{row.is_commander_exemption ? "כן" : "לא"}</td>
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

- [ ] **Step 6: Run test to verify it passes**

Run: `npm test -- ImportSessionReviewPage -t "shows full exemption_type detail fields"`
Expected: PASS.

- [ ] **Step 7: Run the full test file**

Run: `npm test -- ImportSessionReviewPage`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/importSessions.ts frontend/src/pages/ImportSessionReviewPage.tsx frontend/src/pages/ImportSessionReviewPage.test.tsx
git commit -m "feat: show full exemption_type field detail in import review table"
```

---

### Task 5: Frontend — `setFieldOverride` helper + inline editable scalar/boolean fields

**Files:**
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`
- Modify: `frontend/src/pages/ImportSessionReviewPage.test.tsx`

**Interfaces:**
- Produces: `setFieldOverride(group: "duty_types" | "exemption_types" | "shift_templates", row: number, field: string, value: unknown): void`, a page-local function that updates `selections._field_overrides`, debounce-saves via `saveSelections`, and triggers `handleReparse()` on save.

- [ ] **Step 1: Write the failing test**

```tsx
it("edits a duty_type field inline and saves it as a field override", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const detail = makeDraftDetail();
  detail.parsed_state.duty_types = [
    {
      row: 2, action: "new", errors: [], name: "שמירה", score_per_day: "1.50",
      description: "ישן", active: true, reserve_ratio: null, reserve_minimum: null,
      is_external: false, contact_name: null, contact_phone: null,
      start_time: null, end_time: null, instructions: null,
      resolved_eligible_node_ids: [], requirements: null, existing_id: null,
    },
  ];
  vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);
  vi.mocked(importSessionsApi.saveSelections).mockResolvedValue(undefined);
  vi.mocked(importSessionsApi.reparseSession).mockResolvedValue(detail);

  renderPage();
  await screen.findByText("יוסי כהן");
  fireEvent.click(screen.getByText("סוגי תורנות (1)"));

  const input = await screen.findByDisplayValue("ישן");
  fireEvent.change(input, { target: { value: "חדש" } });
  fireEvent.blur(input);
  await vi.advanceTimersByTimeAsync(600);

  expect(importSessionsApi.saveSelections).toHaveBeenCalledWith(
    "session-1",
    expect.objectContaining({
      _field_overrides: { duty_types: { "2": { description: "חדש" } } },
    }),
  );
  vi.useRealTimers();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- ImportSessionReviewPage -t "edits a duty_type field inline"`
Expected: FAIL — the `description` input is `disabled` and has no `onChange`.

- [ ] **Step 3: Add `setFieldOverride` to the component**

In `frontend/src/pages/ImportSessionReviewPage.tsx`, add this function near `setRowAction` (which already exists in the file):

```tsx
function setFieldOverride(
  group: "duty_types" | "exemption_types" | "shift_templates",
  row: number,
  field: string,
  value: unknown,
) {
  if (!id) return;
  setSelections((prev) => {
    const fo = prev._field_overrides ?? {};
    const groupOverrides = (fo as Record<string, Record<string, Record<string, unknown>>>)[group] ?? {};
    const rowOverrides = groupOverrides[String(row)] ?? {};
    const next = {
      ...prev,
      _field_overrides: {
        ...fo,
        [group]: {
          ...groupOverrides,
          [String(row)]: { ...rowOverrides, [field]: value },
        },
      },
    };
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      void saveSelections(id, next).then(() => handleReparse());
    }, 500);
    return next;
  });
}
```

`Selections` (in `api/importSessions.ts`) needs a `_field_overrides` key added to its index signature. Change:

```ts
export interface Selections {
  _name_mappings?: NameMappings;
  [group: string]: Record<string, string> | NameMappings | undefined;
}
```

to:

```ts
export interface Selections {
  _name_mappings?: NameMappings;
  _field_overrides?: Record<string, Record<string, Record<string, unknown>>>;
  [group: string]: Record<string, string> | NameMappings | Record<string, Record<string, Record<string, unknown>>> | undefined;
}
```

- [ ] **Step 4: Wire the duty_types tab's scalar/boolean fields to `setFieldOverride`**

In the duty_types tab table (from Task 3), replace each `disabled` input/cell with a live-editable one, scoped by `!readOnly`:

```tsx
<td className="p-3">
  {readOnly ? row.description ?? "—" : (
    <input
      className="border rounded p-1 text-sm w-40 dark:bg-gray-700 dark:border-gray-600"
      defaultValue={row.description ?? ""}
      onBlur={(e) => setFieldOverride("duty_types", row.row, "description", e.target.value || null)}
    />
  )}
</td>
<td className="p-3">
  {readOnly ? (row.active === null ? "—" : row.active ? "כן" : "לא") : (
    <input
      type="checkbox"
      checked={row.active ?? false}
      onChange={(e) => setFieldOverride("duty_types", row.row, "active", e.target.checked)}
    />
  )}
</td>
<td className="p-3">
  {readOnly ? row.reserve_ratio ?? "—" : (
    <input
      className="border rounded p-1 text-sm w-20 dark:bg-gray-700 dark:border-gray-600"
      defaultValue={row.reserve_ratio ?? ""}
      onBlur={(e) => setFieldOverride("duty_types", row.row, "reserve_ratio", e.target.value || null)}
    />
  )}
</td>
<td className="p-3">
  {readOnly ? row.reserve_minimum ?? "—" : (
    <input
      type="number"
      className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
      defaultValue={row.reserve_minimum ?? ""}
      onBlur={(e) => setFieldOverride("duty_types", row.row, "reserve_minimum", e.target.value ? Number(e.target.value) : null)}
    />
  )}
</td>
<td className="p-3">
  {readOnly ? (row.is_external === null ? "—" : row.is_external ? "כן" : "לא") : (
    <input
      type="checkbox"
      checked={row.is_external ?? false}
      onChange={(e) => setFieldOverride("duty_types", row.row, "is_external", e.target.checked)}
    />
  )}
</td>
<td className="p-3">
  {readOnly ? row.contact_name ?? "—" : (
    <input
      className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
      defaultValue={row.contact_name ?? ""}
      onBlur={(e) => setFieldOverride("duty_types", row.row, "contact_name", e.target.value || null)}
    />
  )}
</td>
<td className="p-3">
  {readOnly ? row.contact_phone ?? "—" : (
    <input
      className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
      defaultValue={row.contact_phone ?? ""}
      onBlur={(e) => setFieldOverride("duty_types", row.row, "contact_phone", e.target.value || null)}
    />
  )}
</td>
<td className="p-3">
  {readOnly ? row.start_time ?? "—" : (
    <input
      className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
      defaultValue={row.start_time ?? ""}
      onBlur={(e) => setFieldOverride("duty_types", row.row, "start_time", e.target.value || null)}
    />
  )}
</td>
<td className="p-3">
  {readOnly ? row.end_time ?? "—" : (
    <input
      className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
      defaultValue={row.end_time ?? ""}
      onBlur={(e) => setFieldOverride("duty_types", row.row, "end_time", e.target.value || null)}
    />
  )}
</td>
<td className="p-3">
  {readOnly ? row.instructions ?? "—" : (
    <textarea
      className="border rounded p-1 text-sm w-40 dark:bg-gray-700 dark:border-gray-600"
      defaultValue={row.instructions ?? ""}
      onBlur={(e) => setFieldOverride("duty_types", row.row, "instructions", e.target.value || null)}
    />
  )}
</td>
```

Also make the `name`/`score_per_day` cells editable the same way (both were plain text so far):

```tsx
<td className="p-3">
  {readOnly ? row.name : (
    <input
      className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
      defaultValue={row.name}
      onBlur={(e) => setFieldOverride("duty_types", row.row, "name", e.target.value)}
    />
  )}
</td>
<td className="p-3">
  {readOnly ? row.score_per_day : (
    <input
      className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
      defaultValue={row.score_per_day ?? ""}
      onBlur={(e) => setFieldOverride("duty_types", row.row, "score_per_day", e.target.value)}
    />
  )}
</td>
```

- [ ] **Step 5: Wire the exemption_types tab's scalar/boolean fields**

In the exemption_types tab table (from Task 4), same pattern:

```tsx
<td className="p-3">
  {readOnly ? row.name : (
    <input
      className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
      defaultValue={row.name}
      onBlur={(e) => setFieldOverride("exemption_types", row.row, "name", e.target.value)}
    />
  )}
</td>
<td className="p-3">
  {readOnly ? row.description ?? "—" : (
    <input
      className="border rounded p-1 text-sm w-40 dark:bg-gray-700 dark:border-gray-600"
      defaultValue={row.description ?? ""}
      onBlur={(e) => setFieldOverride("exemption_types", row.row, "description", e.target.value || null)}
    />
  )}
</td>
<td className="p-3">
  {readOnly ? (row.is_global ? "כן" : "לא") : (
    <input
      type="checkbox"
      checked={row.is_global}
      onChange={(e) => setFieldOverride("exemption_types", row.row, "is_global", e.target.checked)}
    />
  )}
</td>
<td className="p-3">
  {readOnly ? (row.is_medical ? "כן" : "לא") : (
    <input
      type="checkbox"
      checked={row.is_medical}
      onChange={(e) => setFieldOverride("exemption_types", row.row, "is_medical", e.target.checked)}
    />
  )}
</td>
<td className="p-3">
  {readOnly ? (row.is_commander_exemption ? "כן" : "לא") : (
    <input
      type="checkbox"
      checked={row.is_commander_exemption}
      onChange={(e) => setFieldOverride("exemption_types", row.row, "is_commander_exemption", e.target.checked)}
    />
  )}
</td>
```

- [ ] **Step 6: Run test to verify it passes**

Run: `npm test -- ImportSessionReviewPage -t "edits a duty_type field inline"`
Expected: PASS.

- [ ] **Step 7: Run the full test file**

Run: `npm test -- ImportSessionReviewPage`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/importSessions.ts frontend/src/pages/ImportSessionReviewPage.tsx frontend/src/pages/ImportSessionReviewPage.test.tsx
git commit -m "feat: inline-editable scalar/boolean fields for duty_types and exemption_types rows"
```

---

### Task 6: `DutyTypeRequirementsEditor` controlled mode

**Files:**
- Modify: `frontend/src/components/DutyTypeRequirementsEditor.tsx`
- Modify: `frontend/src/components/DutyTypeRequirementsEditor.test.tsx` (check this file exists first — if not, create it following the naming convention of sibling `*.test.tsx` files in the same directory)

**Interfaces:**
- Produces: `DutyTypeRequirementsEditor` accepts either `{ dutyType: DutyType; onSaved: () => void }` (existing, unchanged behavior — writes via `updateDutyTypeRequirements`) or `{ value: Reqs; onChange: (next: Reqs) => void }` (new controlled mode — no API call, just reflects edits to the caller).

- [ ] **Step 1: Write the failing test**

Check `frontend/src/components/DutyTypeRequirementsEditor.test.tsx` for its existing test structure first (`Glob frontend/src/components/DutyTypeRequirementsEditor.test.tsx`). Add:

```tsx
it("renders in controlled mode without calling the API", async () => {
  const onChange = vi.fn();
  render(<DutyTypeRequirementsEditor value={{ officers_allowed: true }} onChange={onChange} />);

  const maleCheckbox = await screen.findByLabelText(/male|זכר/i);
  fireEvent.click(maleCheckbox);

  expect(onChange).toHaveBeenCalled();
  expect(updateDutyTypeRequirements).not.toHaveBeenCalled();
});
```

(Adjust the checkbox label matcher to whatever the existing "gender" checkboxes actually render — check the component's JSX for the exact translation key/text used, e.g. via `t("soldier_profile.gender_male")`; reuse the same matcher style as this file's existing tests.)

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- DutyTypeRequirementsEditor -t "controlled mode"`
Expected: FAIL — `value`/`onChange` props don't exist on the component yet (TypeScript error or runtime prop mismatch).

- [ ] **Step 3: Add the controlled mode**

In `frontend/src/components/DutyTypeRequirementsEditor.tsx`, replace the `Props` interface and component signature:

```tsx
type Reqs = NonNullable<DutyType["requirements"]>;

interface UncontrolledProps {
  dutyType: DutyType;
  onSaved: () => void;
  value?: undefined;
  onChange?: undefined;
}

interface ControlledProps {
  dutyType?: undefined;
  onSaved?: undefined;
  value: Reqs;
  onChange: (next: Reqs) => void;
}

type Props = UncontrolledProps | ControlledProps;

export default function DutyTypeRequirementsEditor(props: Props) {
  const { t } = useTranslation();
  const isControlled = props.value !== undefined;
  const [localReqs, setLocalReqs] = useState<Reqs>(
    isControlled ? props.value : (props.dutyType!.requirements ?? {})
  );
  const reqs = isControlled ? props.value : localReqs;
  const [ranks, setRanks] = useState<{ enlisted: string[]; officers: string[] }>({ enlisted: [], officers: [] });

  useEffect(() => {
    void getRanks().then(setRanks);
  }, []);

  function setReqs(updater: (prev: Reqs) => Reqs) {
    const next = updater(reqs);
    if (isControlled) {
      props.onChange(next);
    } else {
      setLocalReqs(next);
    }
  }

  function toggleItem(key: keyof Reqs, value: string) {
    const current: string[] = (reqs[key] as string[] | undefined) ?? [];
    const next = current.includes(value)
      ? current.filter((v: string) => v !== value)
      : [...current, value];
    setReqs(prev => ({ ...prev, [key]: next }));
  }

  async function save() {
    if (isControlled) return;
    await updateDutyTypeRequirements(props.dutyType!.id, reqs);
    props.onSaved!();
  }
```

Keep the rest of the JSX body as-is (it reads `reqs` and calls `toggleItem`, both still defined) except the final "save" button, which should only render in uncontrolled mode:

```tsx
      {!isControlled && (
        <button onClick={() => void save()}>{t("duty_config.save", "שמור")}</button>
      )}
```

(Find this component's existing save-button JSX at the end of the returned markup and wrap it with the `{!isControlled && (...)}` guard instead of always rendering it.)

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- DutyTypeRequirementsEditor -t "controlled mode"`
Expected: PASS.

- [ ] **Step 5: Run the full test file to check existing (uncontrolled) usage still works**

Run: `npm test -- DutyTypeRequirementsEditor`
Expected: all PASS — existing tests pass `dutyType`/`onSaved` and never see `value`/`onChange`, so `isControlled` is `false` and behavior is unchanged.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DutyTypeRequirementsEditor.tsx frontend/src/components/DutyTypeRequirementsEditor.test.tsx
git commit -m "feat: add controlled value/onChange mode to DutyTypeRequirementsEditor"
```

---

### Task 7: `ImportRowFieldsModal` component (eligible units / requirements / applies-to)

**Files:**
- Create: `frontend/src/components/ImportRowFieldsModal.tsx`
- Create: `frontend/src/components/ImportRowFieldsModal.test.tsx`

**Interfaces:**
- Produces: `ImportRowFieldsModal` — a modal component with three optional sections, each independently shown based on which props are passed:
  - `eligibleUnits?: { value: string[]; onChange: (next: string[]) => void }` — renders `SubHierarchySelector`.
  - `requirements?: { value: Record<string, unknown>; onChange: (next: Record<string, unknown>) => void }` — renders `DutyTypeRequirementsEditor` in controlled mode.
  - `dutyTypeMultiSelect?: { label: string; options: { id: string; name: string }[]; value: string[]; onChange: (next: string[]) => void }` — renders a flat checkbox list (no existing component fits a flat multi-select; built here).
  - `onClose: () => void`.

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import ImportRowFieldsModal from "./ImportRowFieldsModal";

vi.mock("./SubHierarchySelector", () => ({
  default: ({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) => (
    <button onClick={() => onChange([...value, "node-x"])}>toggle-node</button>
  ),
}));

describe("ImportRowFieldsModal", () => {
  it("renders the duty-type multi-select and reports changes", () => {
    const onChange = vi.fn();
    render(
      <ImportRowFieldsModal
        onClose={() => {}}
        dutyTypeMultiSelect={{
          label: "חל על סוגי תורנות",
          options: [{ id: "dt-1", name: "שמירה" }, { id: "dt-2", name: "ליווי" }],
          value: ["dt-1"],
          onChange,
        }}
      />,
    );

    expect(screen.getByText("שמירה")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("ליווי"));
    expect(onChange).toHaveBeenCalledWith(["dt-1", "dt-2"]);
  });

  it("renders eligible units via SubHierarchySelector when provided", () => {
    const onChange = vi.fn();
    render(
      <ImportRowFieldsModal
        onClose={() => {}}
        eligibleUnits={{ value: ["node-1"], onChange }}
      />,
    );
    fireEvent.click(screen.getByText("toggle-node"));
    expect(onChange).toHaveBeenCalledWith(["node-1", "node-x"]);
  });

  it("calls onClose when the close button is clicked", () => {
    const onClose = vi.fn();
    render(<ImportRowFieldsModal onClose={onClose} />);
    fireEvent.click(screen.getByText("✕"));
    expect(onClose).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- ImportRowFieldsModal`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/ImportRowFieldsModal.tsx`:

```tsx
import DutyTypeRequirementsEditor from "./DutyTypeRequirementsEditor";
import SubHierarchySelector from "./SubHierarchySelector";

interface DutyTypeMultiSelect {
  label: string;
  options: { id: string; name: string }[];
  value: string[];
  onChange: (next: string[]) => void;
}

interface EligibleUnits {
  value: string[];
  onChange: (next: string[]) => void;
}

interface Requirements {
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
}

interface Props {
  onClose: () => void;
  eligibleUnits?: EligibleUnits;
  requirements?: Requirements;
  dutyTypeMultiSelect?: DutyTypeMultiSelect;
}

export default function ImportRowFieldsModal({
  onClose,
  eligibleUnits,
  requirements,
  dutyTypeMultiSelect,
}: Props) {
  function toggleDutyType(id: string) {
    if (!dutyTypeMultiSelect) return;
    const { value, onChange } = dutyTypeMultiSelect;
    onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id]);
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-lg max-h-[90dvh] overflow-y-auto space-y-4"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center">
          <h3 className="font-semibold text-base">עריכת שדה</h3>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>

        {eligibleUnits && (
          <div>
            <p className="text-sm font-medium mb-2">יחידות זכאיות</p>
            <SubHierarchySelector value={eligibleUnits.value} onChange={eligibleUnits.onChange} />
          </div>
        )}

        {requirements && (
          <div>
            <p className="text-sm font-medium mb-2">דרישות</p>
            <DutyTypeRequirementsEditor value={requirements.value} onChange={requirements.onChange} />
          </div>
        )}

        {dutyTypeMultiSelect && (
          <div>
            <p className="text-sm font-medium mb-2">{dutyTypeMultiSelect.label}</p>
            <div className="border rounded p-2 max-h-60 overflow-y-auto dark:border-gray-600 space-y-1">
              {dutyTypeMultiSelect.options.map((opt) => (
                <label key={opt.id} className="flex items-center gap-2 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={dutyTypeMultiSelect.value.includes(opt.id)}
                    onChange={() => toggleDutyType(opt.id)}
                  />
                  {opt.name}
                </label>
              ))}
            </div>
          </div>
        )}

        <div className="flex justify-end">
          <button type="button" onClick={onClose} className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700">
            סגור
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- ImportRowFieldsModal`
Expected: all 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ImportRowFieldsModal.tsx frontend/src/components/ImportRowFieldsModal.test.tsx
git commit -m "feat: add ImportRowFieldsModal for editing eligible units, requirements, and applies-to lists"
```

---

### Task 8: Wire `ImportRowFieldsModal` into duty_types and exemption_types tabs

**Files:**
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`
- Modify: `frontend/src/pages/ImportSessionReviewPage.test.tsx`

**Interfaces:**
- Consumes: `ImportRowFieldsModal` (Task 7), `allDutyTypes: LookupItem[]` (already loaded in this page today via `listDutyTypesForImport()`).

- [ ] **Step 1: Write the failing test**

```tsx
it("opens the fields modal and edits eligible units for a duty_type row", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const detail = makeDraftDetail();
  detail.parsed_state.duty_types = [
    {
      row: 2, action: "new", errors: [], name: "שמירה", score_per_day: "1.50",
      description: null, active: true, reserve_ratio: null, reserve_minimum: null,
      is_external: false, contact_name: null, contact_phone: null,
      start_time: null, end_time: null, instructions: null,
      resolved_eligible_node_ids: [], requirements: null, existing_id: null,
    },
  ];
  vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);
  vi.mocked(importSessionsApi.saveSelections).mockResolvedValue(undefined);
  vi.mocked(importSessionsApi.reparseSession).mockResolvedValue(detail);

  renderPage();
  await screen.findByText("יוסי כהן");
  fireEvent.click(screen.getByText("סוגי תורנות (1)"));

  fireEvent.click(await screen.findByText("ערוך יחידות/דרישות"));
  expect(await screen.findByText("יחידות זכאיות")).toBeInTheDocument();
  vi.useRealTimers();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- ImportSessionReviewPage -t "opens the fields modal"`
Expected: FAIL — no such button exists yet.

- [ ] **Step 3: Add modal state and an "edit" button to the duty_types row**

In `frontend/src/pages/ImportSessionReviewPage.tsx`, import the new modal and add state:

```tsx
import ImportRowFieldsModal from "../components/ImportRowFieldsModal";
```

```tsx
const [dutyTypeFieldsRow, setDutyTypeFieldsRow] = useState<DutyTypeImportRow | null>(null);
const [exemptionTypeFieldsRow, setExemptionTypeFieldsRow] = useState<ExemptionTypeImportRow | null>(null);
```

In the duty_types row (from Task 5), add a new cell before the action `<td>`:

```tsx
<td className="p-3">
  {!readOnly && (
    <button
      type="button"
      className="text-indigo-600 hover:underline text-xs"
      onClick={() => setDutyTypeFieldsRow(row)}
    >
      ערוך יחידות/דרישות
    </button>
  )}
</td>
```

Add the corresponding `<th>` header: `<th className="text-right p-3">יחידות/דרישות</th>` right before the "סטטוס" header in the duty_types table.

In the exemption_types row (from Task 5), same pattern:

```tsx
<td className="p-3">
  {!readOnly && (
    <button
      type="button"
      className="text-indigo-600 hover:underline text-xs"
      onClick={() => setExemptionTypeFieldsRow(row)}
    >
      ערוך חל-על
    </button>
  )}
</td>
```

with a matching `<th className="text-right p-3">חל על</th>` header.

- [ ] **Step 4: Render the modal instances**

At the bottom of the component, alongside the existing `{dutyTypeContext && (...)}` and `{nodeCreateContext && (...)}` modal renders, add:

```tsx
{dutyTypeFieldsRow && (
  <ImportRowFieldsModal
    onClose={() => setDutyTypeFieldsRow(null)}
    eligibleUnits={{
      value: dutyTypeFieldsRow.resolved_eligible_node_ids,
      onChange: (next) => {
        setFieldOverride("duty_types", dutyTypeFieldsRow.row, "resolved_eligible_node_ids", next);
        setDutyTypeFieldsRow({ ...dutyTypeFieldsRow, resolved_eligible_node_ids: next });
      },
    }}
    requirements={{
      value: dutyTypeFieldsRow.requirements ?? {},
      onChange: (next) => {
        setFieldOverride("duty_types", dutyTypeFieldsRow.row, "requirements", next);
        setDutyTypeFieldsRow({ ...dutyTypeFieldsRow, requirements: next });
      },
    }}
  />
)}

{exemptionTypeFieldsRow && (
  <ImportRowFieldsModal
    onClose={() => setExemptionTypeFieldsRow(null)}
    dutyTypeMultiSelect={{
      label: "חל על סוגי תורנות",
      options: allDutyTypes,
      value: exemptionTypeFieldsRow.resolved_duty_type_ids,
      onChange: (next) => {
        setFieldOverride("exemption_types", exemptionTypeFieldsRow.row, "resolved_duty_type_ids", next);
        setExemptionTypeFieldsRow({ ...exemptionTypeFieldsRow, resolved_duty_type_ids: next });
      },
    }}
  />
)}
```

(`allDutyTypes` is already loaded by this page's existing `useEffect` calling `listDutyTypesForImport()`.)

- [ ] **Step 5: Run test to verify it passes**

Run: `npm test -- ImportSessionReviewPage -t "opens the fields modal"`
Expected: PASS.

- [ ] **Step 6: Run the full test file and typecheck**

Run: `npm test -- ImportSessionReviewPage && npm run typecheck`
Expected: all PASS, no type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/ImportSessionReviewPage.tsx frontend/src/pages/ImportSessionReviewPage.test.tsx
git commit -m "feat: wire eligible-units/requirements/applies-to editing into import review modals"
```

---

### Task 9: Shift templates — backend schema + parser

**Files:**
- Modify: `backend/app/services/import_parsers/schema.py`
- Modify: `backend/app/services/import_parsers/v1_standard.py`
- Test: `backend/app/services/tests/test_import_parser_v1.py`

**Interfaces:**
- Produces: `ImportShiftTemplateRow` (pydantic model), `ParsedImportData.shift_templates: list[ImportShiftTemplateRow]`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/app/services/tests/test_import_parser_v1.py` (check its existing imports/helpers first with `Read`, then follow the same `_wb_with_*`-style helper convention already used there):

```python
def _wb_with_shift_templates(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("shift_templates")
    ws.append([
        "name", "duty_type_name", "duty_location_name", "recurrence_type", "weekdays",
        "start_time", "end_time", "required_count", "auto_roll", "auto_roll_until",
        "duration_days", "notes", "eligible_units",
    ])
    for r in rows:
        ws.append(r)
    return wb


def test_parses_shift_templates_sheet_row():
    wb = _wb_with_shift_templates([
        ["שמירה לילה", "שמירה", "שער ראשי", "weekly", "1,3",
         "20:00", "06:00", 2, "true", "31.12.2026", 1, "הערה", "מדור א"],
    ])
    data = V1StandardParser().parse(wb)
    assert len(data.shift_templates) == 1
    row = data.shift_templates[0]
    assert row.name == "שמירה לילה"
    assert row.duty_type_name == "שמירה"
    assert row.duty_location_name == "שער ראשי"
    assert row.recurrence_type == "weekly"
    assert row.weekdays == [1, 3]
    assert row.start_time == "20:00"
    assert row.end_time == "06:00"
    assert row.required_count == 2
    assert row.auto_roll is True
    assert row.auto_roll_until == "2026-12-31"
    assert row.duration_days == 1
    assert row.notes == "הערה"
    assert row.eligible_unit_names == ["מדור א"]


def test_shift_templates_sheet_absent_gives_empty_list():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    data = V1StandardParser().parse(wb)
    assert data.shift_templates == []


def test_shift_templates_row_defaults():
    wb = _wb_with_shift_templates([
        ["שמירה", "שמירה", "שער ראשי", "", "", "", "", "", "", "", "", "", ""],
    ])
    data = V1StandardParser().parse(wb)
    row = data.shift_templates[0]
    assert row.recurrence_type == "weekdays"
    assert row.weekdays == []
    assert row.required_count == 1
    assert row.auto_roll is False
    assert row.duration_days == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_import_parser_v1.py -v -k "shift_templates"`
Expected: FAIL — `data.shift_templates` doesn't exist.

- [ ] **Step 3: Add `ImportShiftTemplateRow` to the schema**

In `backend/app/services/import_parsers/schema.py`, add (after `ImportDutyTypeRow`, before `ImportExemptionTypeRow`):

```python
class ImportShiftTemplateRow(BaseModel):
    source_row: int
    name: str
    duty_type_name: str
    duty_location_name: str
    recurrence_type: str = "weekdays"
    weekdays: list[int] = []
    start_time: str | None = None
    end_time: str | None = None
    required_count: int = 1
    auto_roll: bool = False
    auto_roll_until: str | None = None
    duration_days: int = 1
    notes: str | None = None
    eligible_unit_names: list[str] = []
```

Change `ParsedImportData` to add the field (alongside the existing `assignments`, `duty_types`, etc.):

```python
class ParsedImportData(BaseModel):
    soldiers: list[ImportSoldierRow] = []
    duty_shifts: list[ImportDutyShiftRow] = []
    duty_locations: list[ImportDutyLocationRow] = []
    hierarchy: list[ImportHierarchyNodeRow] = []
    duty_types: list[ImportDutyTypeRow] = []
    shift_templates: list[ImportShiftTemplateRow] = []
    exemption_types: list[ImportExemptionTypeRow] = []
    assignments: list[ImportAssignmentRow] = []
    parser_id: str
    parser_warnings: list[str] = []
```

(Preserve the existing field order otherwise — only inserting `shift_templates` as a new line. Verify the exact current field list first with `Read` since it may have drifted slightly from this listing.)

- [ ] **Step 4: Parse the sheet in `v1_standard.py`**

In `backend/app/services/import_parsers/v1_standard.py`:

Update the import block:

```python
from app.services.import_parsers.schema import (
    ImportAssignmentRow,
    ImportDutyLocationRow,
    ImportDutyShiftRow,
    ImportDutyTypeRow,
    ImportExemptionTypeRow,
    ImportHierarchyNodeRow,
    ImportNodeQuota,
    ImportShiftTemplateRow,
    ImportSoldierRow,
    ParsedImportData,
)
```

Update `KNOWN_SHEETS`:

```python
KNOWN_SHEETS = {
    "soldiers", "duty_shifts", "assignments", "duty_locations", "hierarchy",
    "duty_types", "exemption_types", "shift_templates",
}
```

Add a helper for parsing the `weekdays` cell (comma-separated ints), placed next to `_parse_name_list`:

```python
def _parse_int_list(raw: Any) -> list[int]:
    """Parse a comma-separated list of integers (used for `weekdays`).

    Non-integer entries are skipped silently — malformed weekday values are
    caught by the resolver's recurrence_type/weekdays validation, not here.
    """
    s = str(raw or "").strip()
    if not s:
        return []
    out = []
    for part in s.split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out
```

Add the shift_templates parsing block in `V1StandardParser.parse()`, right before the `return ParsedImportData(...)` statement:

```python
        shift_templates = [
            ImportShiftTemplateRow(
                source_row=r["_row"],
                name=str(r.get("name") or "").strip(),
                duty_type_name=str(r.get("duty_type_name") or "").strip(),
                duty_location_name=str(r.get("duty_location_name") or "").strip(),
                recurrence_type=str(r.get("recurrence_type") or "").strip() or "weekdays",
                weekdays=_parse_int_list(r.get("weekdays")),
                start_time=str(r.get("start_time") or "").strip() or None,
                end_time=str(r.get("end_time") or "").strip() or None,
                required_count=int(r.get("required_count") or 1),
                auto_roll=_parse_bool(r.get("auto_roll")) or False,
                auto_roll_until=_parse_date(r.get("auto_roll_until")),
                duration_days=int(r.get("duration_days") or 1),
                notes=str(r.get("notes") or "").strip() or None,
                eligible_unit_names=_parse_name_list(r.get("eligible_units")),
            )
            for r in _sheet_rows(wb, "shift_templates")
        ]
```

And add `shift_templates=shift_templates,` to the `ParsedImportData(...)` call.

Also update the class docstring (it currently says shift templates are "not importable via Excel" — that's now false):

```python
class V1StandardParser:
    """Standard v1 layout: `soldiers`, `duty_shifts`, `assignments`,
    `duty_locations`, `hierarchy`, `duty_types`, `exemption_types`,
    `shift_templates`.
    """
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_import_parser_v1.py -v -k "shift_templates"`
Expected: all 3 PASS.

- [ ] **Step 6: Run the full parser test file**

Run: `cd backend && pytest app/services/tests/test_import_parser_v1.py -v`
Expected: all PASS (pre-existing tests unaffected — `shift_templates` defaults to `[]` when absent).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/import_parsers/schema.py backend/app/services/import_parsers/v1_standard.py backend/app/services/tests/test_import_parser_v1.py
git commit -m "feat: parse shift_templates sheet into ImportShiftTemplateRow"
```

---

### Task 10: Shift templates — resolver rewrite

**Files:**
- Modify: `backend/app/services/import_sessions.py` (`_resolve_shift_templates`, `_resolve_and_score`)
- Test: `backend/app/services/tests/test_import_sessions_service.py`

**Interfaces:**
- Consumes: `ParsedImportData.shift_templates` (Task 9).
- Produces: `_resolve_shift_templates(session, data, dt_by_name=None, dt_by_row=None, node_by_name=None, node_by_row=None, overrides=None) -> list[dict]`, each dict: `row, action, errors, name, duty_type_name, resolved_duty_type_id, duty_location_name, resolved_duty_location_id, recurrence_type, weekdays, start_time, end_time, required_count, auto_roll, auto_roll_until, duration_days, notes, resolved_eligible_node_ids, existing_id`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/app/services/tests/test_import_sessions_service.py`:

```python
def _wb_with_shift_templates(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("shift_templates")
    ws.append([
        "name", "duty_type_name", "duty_location_name", "recurrence_type", "weekdays",
        "start_time", "end_time", "required_count", "auto_roll", "auto_roll_until",
        "duration_days", "notes", "eligible_units",
    ])
    for r in rows:
        ws.append(r)
    return wb


def test_shift_template_resolves_duty_type_and_location(admin_session):
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.commit()

    wb = _wb_with_shift_templates([
        [f"tpl_{_uid()}", dt.name, loc.name, "weekdays", "", "08:00", "17:00", 1, "false", "", 1, "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row = sess.parsed_state["shift_templates"][0]
    assert row["action"] == "new"
    assert row["resolved_duty_type_id"] == str(dt.id)
    assert row["resolved_duty_location_id"] == str(loc.id)


def test_shift_template_unresolved_duty_type_errors(admin_session):
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.commit()

    wb = _wb_with_shift_templates([
        [f"tpl_{_uid()}", "לא קיים", loc.name, "weekdays", "", "", "", 1, "false", "", 1, "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row = sess.parsed_state["shift_templates"][0]
    assert row["action"] == "error"
    assert any("סוג תורנות לא מזוהה" in e for e in row["errors"])


def test_shift_template_matches_existing_by_name_for_update(admin_session):
    from app.services.shift_templates import create_template

    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    tpl_name = f"tpl_{_uid()}"
    create_template(
        admin_session, name=tpl_name, duty_type_id=dt.id, duty_location_id=loc.id,
        recurrence_type="weekdays", weekdays=[],
    )
    admin_session.commit()

    wb = _wb_with_shift_templates([
        [tpl_name, dt.name, loc.name, "weekdays", "", "", "", 2, "false", "", 1, "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row = sess.parsed_state["shift_templates"][0]
    assert row["action"] == "update"
    assert row["existing_id"] is not None


def test_shift_template_eligible_unit_resolution(admin_session):
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    node = create_node(admin_session, level="branch", name=f"node_{_uid()}")
    admin_session.commit()

    wb = _wb_with_shift_templates([
        [f"tpl_{_uid()}", dt.name, loc.name, "weekdays", "", "", "", 1, "false", "", 1, "", node.name],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row = sess.parsed_state["shift_templates"][0]
    assert row["resolved_eligible_node_ids"] == [str(node.id)]


def test_shift_template_field_override_changes_resolved_name(admin_session):
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.commit()

    wb = _wb_with_shift_templates([
        [f"tpl_{_uid()}", dt.name, loc.name, "weekdays", "", "", "", 1, "false", "", 1, "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row_num = sess.parsed_state["shift_templates"][0]["row"]

    set_selections(admin_session, session_id=sess.id, selections={
        "_field_overrides": {"shift_templates": {str(row_num): {"required_count": 5}}},
    })
    admin_session.commit()

    reparse_session(admin_session, session_id=sess.id, actor=admin)
    row = sess.parsed_state["shift_templates"][0]
    assert row["required_count"] == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_import_sessions_service.py -v -k "shift_template"`
Expected: FAIL — current `_resolve_shift_templates` always sees `[]` (dead `getattr` fallback), so `resolved_duty_type_id`/`resolved_duty_location_id`/etc. don't match.

- [ ] **Step 3: Rewrite `_resolve_shift_templates`**

In `backend/app/services/import_sessions.py`, replace the entire current body of `_resolve_shift_templates` (lines 538-578):

```python
def _resolve_shift_templates(
    session: Session,
    data: ParsedImportData,
    dt_by_name: dict[str, str] | None = None,
    dt_by_row: dict[str, str] | None = None,
    node_by_name: dict[str, str] | None = None,
    node_by_row: dict[str, str] | None = None,
    overrides: dict[str, dict] | None = None,
) -> list[dict]:
    dt_by_name = dt_by_name or {}
    dt_by_row = dt_by_row or {}
    node_by_name = node_by_name or {}
    node_by_row = node_by_row or {}
    overrides = overrides or {}
    duty_types_by_name = {dt.name: dt for dt in session.execute(select(DutyType)).scalars()}
    locations_by_name = {loc.name: loc for loc in session.execute(select(DutyLocation)).scalars()}
    nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}
    existing_by_name = {tpl.name: tpl for tpl in session.execute(select(ShiftTemplate)).scalars()}

    out = []
    for row in data.shift_templates:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        name = field("name", row.name)
        duty_type_name = field("duty_type_name", row.duty_type_name)
        duty_location_name = field("duty_location_name", row.duty_location_name)
        recurrence_type = field("recurrence_type", row.recurrence_type)
        eligible_unit_names = field("eligible_unit_names", row.eligible_unit_names)

        duty_type = None
        if duty_type_name:
            row_key = f"shift_templates:{row.source_row}"
            mapped_id = dt_by_row.get(row_key) or dt_by_name.get(duty_type_name)
            if mapped_id:
                try:
                    duty_type = session.get(DutyType, uuid.UUID(mapped_id))
                except ValueError:
                    pass
            if duty_type is None:
                duty_type = duty_types_by_name.get(duty_type_name)
        if duty_type is None:
            errors.append(f"סוג תורנות לא מזוהה '{duty_type_name}'")

        location = locations_by_name.get(duty_location_name) if duty_location_name else None
        if location is None:
            errors.append(f"מיקום תורנות לא מזוהה '{duty_location_name}'")

        if recurrence_type not in ("daily", "weekdays", "weekly"):
            errors.append(f"סוג חזרתיות לא תקין '{recurrence_type}'")

        resolved_eligible_node_ids: list[str] | None = field("resolved_eligible_node_ids", None)
        if resolved_eligible_node_ids is None:
            resolved_eligible_node_ids = []
            for unit_name in eligible_unit_names:
                row_key = f"shift_templates:{row.source_row}:{unit_name}"
                mapped_id = node_by_row.get(row_key) or node_by_name.get(unit_name)
                node = None
                if mapped_id:
                    try:
                        node = session.get(HierarchyNode, uuid.UUID(mapped_id))
                    except ValueError:
                        pass
                if node is None:
                    node = nodes_by_name.get(unit_name)
                if node is None:
                    errors.append(f"יחידה זכאית לא מזוהה '{unit_name}'")
                else:
                    resolved_eligible_node_ids.append(str(node.id))

        existing = existing_by_name.get(name) if name else None
        action = "error" if errors else ("update" if existing else "new")

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "name": name,
            "duty_type_name": duty_type_name,
            "resolved_duty_type_id": str(duty_type.id) if duty_type is not None else None,
            "duty_location_name": duty_location_name,
            "resolved_duty_location_id": str(location.id) if location is not None else None,
            "recurrence_type": recurrence_type,
            "weekdays": field("weekdays", row.weekdays),
            "start_time": field("start_time", row.start_time),
            "end_time": field("end_time", row.end_time),
            "required_count": field("required_count", row.required_count),
            "auto_roll": field("auto_roll", row.auto_roll),
            "auto_roll_until": field("auto_roll_until", row.auto_roll_until),
            "duration_days": field("duration_days", row.duration_days),
            "notes": field("notes", row.notes),
            "resolved_eligible_node_ids": resolved_eligible_node_ids,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out
```

Add `ShiftTemplate` to the `app.db.models` import block at the top of the file (alongside `DutyAssignment`, `DutyLocation`, etc.):

```python
from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyManagerScope,
    DutyShift,
    DutyType,
    ExemptionType,
    HierarchyLevelType,
    HierarchyNode,
    ImportSession,
    ShiftTemplate,
    Soldier,
)
```

- [ ] **Step 4: Wire it into `_resolve_and_score`**

In `_resolve_and_score`, replace the `shift_templates` call:

```python
"shift_templates": _resolve_shift_templates(
    session, data, dt_by_name, dt_by_row, node_by_name, node_by_row, fo.get("shift_templates", {})
),
```

(This is the same line changed in Task 2 Step 5 — if that step already landed, this replaces the interim `_resolve_shift_templates(session, data, dt_by_name, dt_by_row)` call with the fuller signature.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_import_sessions_service.py -v -k "shift_template"`
Expected: all 5 PASS.

- [ ] **Step 6: Run the full service test file**

Run: `cd backend && pytest app/services/tests/test_import_sessions_service.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/import_sessions.py backend/app/services/tests/test_import_sessions_service.py
git commit -m "feat: resolve shift_templates sheet rows against duty types, locations, and eligible units"
```

---

### Task 11: Shift templates — confirm loop

**Files:**
- Modify: `backend/app/services/import_sessions.py` (`confirm_session`)
- Test: `backend/app/services/tests/test_import_sessions_service.py`

**Interfaces:**
- Consumes: `state["shift_templates"]` rows from Task 10, `app.services.shift_templates.create_template`/`update_template`.
- Produces: `confirm_session()` creates/updates `ShiftTemplate` rows; `created_links["shift_templates"]: list[str]` added.

- [ ] **Step 1: Write the failing tests**

Add to `backend/app/services/tests/test_import_sessions_service.py`:

```python
def test_confirm_session_creates_shift_template(admin_session):
    from app.db.models import ShiftTemplate as ShiftTemplateModel

    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.commit()

    tpl_name = f"tpl_{_uid()}"
    wb = _wb_with_shift_templates([
        [tpl_name, dt.name, loc.name, "weekdays", "", "08:00", "17:00", 2, "false", "", 1, "note", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    admin_session.commit()

    result = confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    assert result["created"] == 1
    assert len(sess.created_links["shift_templates"]) == 1
    created = admin_session.get(ShiftTemplateModel, uuid.UUID(sess.created_links["shift_templates"][0]))
    assert created is not None
    assert created.name == tpl_name
    assert created.duty_type_id == dt.id
    assert created.required_count == 2
    assert created.notes == "note"


def test_confirm_session_updates_existing_shift_template(admin_session):
    from app.services.shift_templates import create_template

    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    tpl_name = f"tpl_{_uid()}"
    tpl = create_template(
        admin_session, name=tpl_name, duty_type_id=dt.id, duty_location_id=loc.id,
        recurrence_type="weekdays", weekdays=[], required_count=1,
    )
    admin_session.commit()

    wb = _wb_with_shift_templates([
        [tpl_name, dt.name, loc.name, "weekdays", "", "", "", 3, "false", "", 1, "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    admin_session.commit()

    result = confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    assert result["updated"] == 1
    admin_session.refresh(tpl)
    assert tpl.required_count == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_import_sessions_service.py -v -k "confirm_session_creates_shift_template or confirm_session_updates_existing_shift_template"`
Expected: FAIL — `sess.created_links["shift_templates"]` `KeyError` (no confirm loop yet).

- [ ] **Step 3: Add the confirm loop**

In `backend/app/services/import_sessions.py`, add `create_template`/`update_template` to the service imports:

```python
from app.services.shift_templates import create_template, update_template
```

In `confirm_session`, add `created_shift_templates: list[str] = []` to the initial declarations block (alongside `created_soldiers`, `created_duty_shifts`, `created_assignments`):

```python
    created_soldiers: list[str] = []
    created_duty_shifts: list[str] = []
    created_assignments: list[str] = []
    created_shift_templates: list[str] = []
    shift_row_to_id: dict[int, uuid.UUID] = {}
```

Insert a new loop right after the "Duty types" loop ends (after line 1103, i.e. right before the `# ── Hierarchy ──` comment):

```python
    # ── Shift templates ─────────────────────────────────────────────────
    for row in state.get("shift_templates", []):
        effective = _effective_action(selections, "shift_templates", row)
        if row["action"] == "error" or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                eligible_ids = [uuid.UUID(nid) for nid in row.get("resolved_eligible_node_ids", [])] or None
                if effective == "new":
                    tpl = create_template(
                        session,
                        name=row["name"],
                        duty_type_id=uuid.UUID(row["resolved_duty_type_id"]),
                        duty_location_id=uuid.UUID(row["resolved_duty_location_id"]),
                        recurrence_type=row["recurrence_type"],
                        weekdays=row.get("weekdays") or [],
                        duration_days=row.get("duration_days") or 1,
                        start_time=row.get("start_time") or "00:00",
                        end_time=row.get("end_time") or "23:59",
                        required_count=row.get("required_count") or 1,
                        auto_roll=bool(row.get("auto_roll")),
                        auto_roll_until=(
                            date_type.fromisoformat(row["auto_roll_until"])
                            if row.get("auto_roll_until") else None
                        ),
                        notes=row.get("notes"),
                        eligible_node_ids=eligible_ids,
                        actor_id=actor.id,
                    )
                    created += 1
                    created_shift_templates.append(str(tpl.id))
                elif effective == "update" and row.get("existing_id"):
                    tpl = session.get(ShiftTemplate, uuid.UUID(row["existing_id"]))
                    if tpl is not None:
                        update_template(
                            session,
                            tpl=tpl,
                            recurrence_type=row.get("recurrence_type"),
                            weekdays=row.get("weekdays"),
                            duration_days=row.get("duration_days"),
                            start_time=row.get("start_time"),
                            end_time=row.get("end_time"),
                            required_count=row.get("required_count"),
                            auto_roll=row.get("auto_roll"),
                            auto_roll_until=(
                                date_type.fromisoformat(row["auto_roll_until"])
                                if row.get("auto_roll_until") else None
                            ),
                            notes=row.get("notes"),
                            eligible_node_ids=eligible_ids,
                            actor_id=actor.id,
                        )
                        updated += 1
                        created_shift_templates.append(str(tpl.id))
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "shift_templates", "error": str(exc)})
```

Update `import_session.created_links` to include the new key:

```python
    import_session.created_links = {
        "soldiers": created_soldiers,
        "duty_shifts": created_duty_shifts,
        "assignments": created_assignments,
        "shift_templates": created_shift_templates,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_import_sessions_service.py -v -k "shift_template"`
Expected: all PASS (7 total: 5 from Task 10 + 2 new).

- [ ] **Step 5: Run the full service test file**

Run: `cd backend && pytest app/services/tests/test_import_sessions_service.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/import_sessions.py backend/app/services/tests/test_import_sessions_service.py
git commit -m "feat: create/update ShiftTemplate rows when confirming an import session"
```

---

### Task 12: Shift templates — template download + export sheet

**Files:**
- Modify: `backend/app/routes/import_excel.py` (`download_template`, `export_current_data`)
- Test: `backend/tests/integration/test_import_excel.py`

**Interfaces:**
- Extends: `GET /import/template` and `GET /import/export` responses with a `shift_templates` sheet.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/integration/test_import_excel.py` (check its existing imports/fixtures first):

```python
def test_template_download_includes_shift_templates_sheet(client, admin_session):
    node = create_node(admin_session, level="branch", name="ie_node_005")
    dm = create_soldier(admin_session, personal_number="ie_dm_005", role="duty_manager", hierarchy_node_id=node.id)
    token = auth_headers(dm)["Authorization"].split(" ", 1)[1]
    resp = client.get("/api/import/template", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200

    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert "shift_templates" in wb.sheetnames
    headers = [c.value for c in next(wb["shift_templates"].iter_rows(min_row=1, max_row=1))]
    assert headers == [
        "name", "duty_type_name", "duty_location_name", "recurrence_type", "weekdays",
        "start_time", "end_time", "required_count", "auto_roll", "auto_roll_until",
        "duration_days", "notes", "eligible_units",
    ]


def test_export_current_data_includes_shift_templates(client, admin_session):
    from app.services.shift_templates import create_template
    from app.db.models import DutyLocation

    dt = create_duty_type(admin_session, name=f"dt_export_{uuid.uuid4().hex[:8]}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_export_{uuid.uuid4().hex[:8]}")
    admin_session.add(loc)
    admin_session.flush()
    tpl_name = f"tpl_export_{uuid.uuid4().hex[:8]}"
    create_template(
        admin_session, name=tpl_name, duty_type_id=dt.id, duty_location_id=loc.id,
        recurrence_type="weekdays", weekdays=[], required_count=1,
    )
    admin_session.commit()

    admin = create_soldier(admin_session, personal_number=f"adm_export_{uuid.uuid4().hex[:8]}", role="admin")
    token = auth_headers(admin)["Authorization"].split(" ", 1)[1]
    resp = client.get("/api/import/export", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200

    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert "shift_templates" in wb.sheetnames
    rows = list(wb["shift_templates"].iter_rows(min_row=2, values_only=True))
    names = [r[0] for r in rows]
    assert tpl_name in names
```

(Adjust import statements — `uuid`, `Decimal`, `create_duty_type`, `create_soldier`, `auth_headers` — to match whatever this test file already imports; check with `Read` first rather than assuming.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/integration/test_import_excel.py -v -k "shift_templates"`
Expected: FAIL — no `shift_templates` sheet in either response yet.

- [ ] **Step 3: Add the sheet to `download_template`**

In `backend/app/routes/import_excel.py`, add after the `ws_et` block (exemption_types example sheet), before `buf = io.BytesIO()`:

```python
    ws_tpl = wb.create_sheet("shift_templates")
    ws_tpl.append([
        "name", "duty_type_name", "duty_location_name", "recurrence_type", "weekdays",
        "start_time", "end_time", "required_count", "auto_roll", "auto_roll_until",
        "duration_days", "notes", "eligible_units",
    ])
    ws_tpl.append([
        "שמירה לילה", "שמירה", "שער ראשי", "weekly", "1,3",
        "20:00", "06:00", 2, "false", "", 1, "", "מדור א",
    ])
```

Update the `download_template()` docstring to mention `shift_templates` is now a real sheet (remove the "intentionally not included" note, since Task 9 made it importable):

```python
def download_template():
    """Download an example workbook for the active import pipeline.

    Matches the `v1_standard` parser's expected sheets — see
    app/services/import_parsers/v1_standard.py.
    """
```

- [ ] **Step 4: Add the sheet to `export_current_data`**

In the same file, in `export_current_data`, add `ShiftTemplate` to the model imports:

```python
from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyShift,
    DutyShiftNodeQuota,
    DutyType,
    HierarchyNode,
    ShiftTemplate,
    Soldier,
)
```

Add a shift_templates export block right after the `ws_a` (assignments) block, before `buf = io.BytesIO()`:

```python
    ws_tpl = wb.create_sheet("shift_templates")
    ws_tpl.append([
        "name", "duty_type_name", "duty_location_name", "recurrence_type", "weekdays",
        "start_time", "end_time", "required_count", "auto_roll", "auto_roll_until",
        "duration_days", "notes", "eligible_units",
    ])
    for tpl in session.execute(select(ShiftTemplate)).scalars():
        dt = duty_types_by_id.get(tpl.duty_type_id)
        loc = locations_by_id.get(tpl.duty_location_id)
        eligible = ", ".join(
            nodes_by_id[nid].name for nid in (tpl.eligible_node_ids or []) if nid in nodes_by_id
        )
        ws_tpl.append([
            tpl.name,
            dt.name if dt else "",
            loc.name if loc else "",
            tpl.recurrence_type,
            ",".join(str(d) for d in tpl.weekdays),
            tpl.start_time, tpl.end_time, tpl.required_count,
            "true" if tpl.auto_roll else "false",
            tpl.auto_roll_until.strftime("%d.%m.%Y") if tpl.auto_roll_until else "",
            tpl.duration_days,
            tpl.notes or "",
            eligible,
        ])
```

(`duty_types_by_id`, `locations_by_id`, and `nodes_by_id` are already built earlier in `export_current_data` for the `duty_shifts`/`assignments` sheets — reuse them, don't rebuild.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_import_excel.py -v -k "shift_templates"`
Expected: both PASS.

- [ ] **Step 6: Run the full integration test file**

Run: `cd backend && pytest tests/integration/test_import_excel.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/import_excel.py backend/tests/integration/test_import_excel.py
git commit -m "feat: add shift_templates sheet to import template and full-data export"
```

---

### Task 13: Frontend — shift_templates tab (full detail + inline edit)

**Files:**
- Modify: `frontend/src/api/importSessions.ts`
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`
- Modify: `frontend/src/pages/ImportSessionReviewPage.test.tsx`

**Interfaces:**
- Produces: `ShiftTemplateRow` replaces its stale `days_of_week`/`required_primary`/`required_reserve` fields with the real shape returned by Task 10's resolver.

- [ ] **Step 1: Replace the stale `ShiftTemplateRow` TS interface**

In `frontend/src/api/importSessions.ts`, replace:

```ts
export interface ShiftTemplateRow extends RowBase {
  name: string;
  duty_type_name: string;
  resolved_duty_type_id: string | null;
  days_of_week: number[];
  required_primary: number;
  required_reserve: number;
}
```

with:

```ts
export interface ShiftTemplateRow extends RowBase {
  name: string;
  duty_type_name: string;
  resolved_duty_type_id: string | null;
  duty_location_name: string;
  resolved_duty_location_id: string | null;
  recurrence_type: string;
  weekdays: number[];
  start_time: string | null;
  end_time: string | null;
  required_count: number;
  auto_roll: boolean;
  auto_roll_until: string | null;
  duration_days: number;
  notes: string | null;
  resolved_eligible_node_ids: string[];
  existing_id: string | null;
}
```

- [ ] **Step 2: Write the failing test**

Add to `frontend/src/pages/ImportSessionReviewPage.test.tsx`:

```tsx
it("renders full shift_template detail and allows inline edits", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const detail = makeDraftDetail();
  detail.parsed_state.shift_templates = [
    {
      row: 2, action: "new", errors: [],
      name: "שמירה לילה", duty_type_name: "שמירה", resolved_duty_type_id: "dt-1",
      duty_location_name: "שער ראשי", resolved_duty_location_id: "loc-1",
      recurrence_type: "weekly", weekdays: [1, 3],
      start_time: "20:00", end_time: "06:00", required_count: 2,
      auto_roll: false, auto_roll_until: null, duration_days: 1,
      notes: null, resolved_eligible_node_ids: [], existing_id: null,
    },
  ];
  vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);
  vi.mocked(importSessionsApi.saveSelections).mockResolvedValue(undefined);
  vi.mocked(importSessionsApi.reparseSession).mockResolvedValue(detail);

  renderPage();
  await screen.findByText("יוסי כהן");
  fireEvent.click(screen.getByText("תבניות (1)"));

  const countInput = await screen.findByDisplayValue("2");
  fireEvent.change(countInput, { target: { value: "5" } });
  fireEvent.blur(countInput);
  await vi.advanceTimersByTimeAsync(600);

  expect(importSessionsApi.saveSelections).toHaveBeenCalledWith(
    "session-1",
    expect.objectContaining({
      _field_overrides: { shift_templates: { "2": { required_count: 5 } } },
    }),
  );
  vi.useRealTimers();
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npm test -- ImportSessionReviewPage -t "renders full shift_template detail"`
Expected: FAIL — the current shift_templates tab reads `days_of_week`/`required_primary`, which no longer exist on the fixture.

- [ ] **Step 4: Replace the shift_templates tab**

Replace the entire `{tab === "shift_templates" && (...)}` block (currently lines 700-805) with:

```tsx
{tab === "shift_templates" && (
  <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
    <table className="w-full text-sm">
      <thead>
        <tr className="text-gray-500 border-b dark:border-gray-700">
          <th className="text-right p-3">שם</th>
          <th className="text-right p-3">סוג תורנות</th>
          <th className="text-right p-3">מיקום</th>
          <th className="text-right p-3">חזרתיות</th>
          <th className="text-right p-3">ימים</th>
          <th className="text-right p-3">שעת התחלה</th>
          <th className="text-right p-3">שעת סיום</th>
          <th className="text-right p-3">נדרש</th>
          <th className="text-right p-3">גלגול אוטומטי</th>
          <th className="text-right p-3">עד תאריך</th>
          <th className="text-right p-3">משך (ימים)</th>
          <th className="text-right p-3">הערות</th>
          <th className="text-right p-3">יחידות זכאיות</th>
          <th className="text-right p-3">סטטוס</th>
          {!readOnly && <th className="text-right p-3">פעולה</th>}
        </tr>
      </thead>
      <tbody>
        {shift_templates.map((row: ShiftTemplateRow) => {
          const canToggle = row.action !== "error" && row.action !== "out_of_scope";
          const unresolvedType = !row.resolved_duty_type_id;
          return (
            <tr key={row.row} className="border-b dark:border-gray-700">
              <td className="p-3">
                {readOnly ? row.name : (
                  <input
                    className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                    defaultValue={row.name}
                    onBlur={(e) => setFieldOverride("shift_templates", row.row, "name", e.target.value)}
                  />
                )}
              </td>
              <td className="p-3">
                {unresolvedType ? (
                  <div className="flex flex-col gap-1">
                    <span className="text-red-600 text-xs font-medium">{row.duty_type_name}</span>
                    {!readOnly && (
                      <Combobox
                        items={buildPickerItems(row.duty_type_name, allDutyTypes, sortedDutyTypeItems)}
                        value=""
                        onChange={(pickedId) => {
                          if (pickedId)
                            handlePick("duty_type", row.duty_type_name, `shift_templates:${row.row}`, pickedId);
                        }}
                      />
                    )}
                    {pendingPick?.rowKey === `shift_templates:${row.row}` && pendingPick.kind === "duty_type" && (
                      <PendingPickBanner
                        pick={pendingPick}
                        onApplyAll={() => void applyMapping("all", pendingPick)}
                        onApplyRow={() => void applyMapping("row", pendingPick)}
                        onCancel={() => setPendingPick(null)}
                      />
                    )}
                  </div>
                ) : (
                  row.duty_type_name
                )}
              </td>
              <td className="p-3">{row.duty_location_name}</td>
              <td className="p-3">
                {readOnly ? row.recurrence_type : (
                  <select
                    className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                    defaultValue={row.recurrence_type}
                    onChange={(e) => setFieldOverride("shift_templates", row.row, "recurrence_type", e.target.value)}
                  >
                    <option value="weekdays">א׳-ה׳</option>
                    <option value="daily">יומי</option>
                    <option value="weekly">שבועי (ימים נבחרים)</option>
                  </select>
                )}
              </td>
              <td className="p-3">
                {row.recurrence_type !== "weekly" ? "—" : readOnly ? row.weekdays.join(",") : (
                  <div className="flex gap-1">
                    {[1, 2, 3, 4, 5, 6, 7].map((iso) => (
                      <button
                        key={iso}
                        type="button"
                        className={`w-6 h-6 rounded text-xs border ${
                          row.weekdays.includes(iso)
                            ? "bg-indigo-600 text-white border-indigo-600"
                            : "bg-white dark:bg-gray-700 text-gray-600 dark:text-gray-300 border-gray-300 dark:border-gray-600"
                        }`}
                        onClick={() => {
                          const next = row.weekdays.includes(iso)
                            ? row.weekdays.filter((d) => d !== iso)
                            : [...row.weekdays, iso].sort((a, b) => a - b);
                          setFieldOverride("shift_templates", row.row, "weekdays", next);
                        }}
                      >
                        {iso}
                      </button>
                    ))}
                  </div>
                )}
              </td>
              <td className="p-3">
                {readOnly ? row.start_time ?? "—" : (
                  <input
                    className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                    defaultValue={row.start_time ?? ""}
                    onBlur={(e) => setFieldOverride("shift_templates", row.row, "start_time", e.target.value || null)}
                  />
                )}
              </td>
              <td className="p-3">
                {readOnly ? row.end_time ?? "—" : (
                  <input
                    className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                    defaultValue={row.end_time ?? ""}
                    onBlur={(e) => setFieldOverride("shift_templates", row.row, "end_time", e.target.value || null)}
                  />
                )}
              </td>
              <td className="p-3">
                {readOnly ? row.required_count : (
                  <input
                    type="number"
                    className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                    defaultValue={row.required_count}
                    onBlur={(e) => setFieldOverride("shift_templates", row.row, "required_count", Number(e.target.value))}
                  />
                )}
              </td>
              <td className="p-3">
                {readOnly ? (row.auto_roll ? "כן" : "לא") : (
                  <input
                    type="checkbox"
                    checked={row.auto_roll}
                    onChange={(e) => setFieldOverride("shift_templates", row.row, "auto_roll", e.target.checked)}
                  />
                )}
              </td>
              <td className="p-3">
                {!row.auto_roll ? "—" : readOnly ? row.auto_roll_until ?? "—" : (
                  <input
                    type="date"
                    className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                    defaultValue={row.auto_roll_until ?? ""}
                    onBlur={(e) => setFieldOverride("shift_templates", row.row, "auto_roll_until", e.target.value || null)}
                  />
                )}
              </td>
              <td className="p-3">
                {readOnly ? row.duration_days : (
                  <input
                    type="number"
                    className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                    defaultValue={row.duration_days}
                    onBlur={(e) => setFieldOverride("shift_templates", row.row, "duration_days", Number(e.target.value))}
                  />
                )}
              </td>
              <td className="p-3">
                {readOnly ? row.notes ?? "—" : (
                  <textarea
                    className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                    defaultValue={row.notes ?? ""}
                    onBlur={(e) => setFieldOverride("shift_templates", row.row, "notes", e.target.value || null)}
                  />
                )}
              </td>
              <td className="p-3">
                {!readOnly && (
                  <button
                    type="button"
                    className="text-indigo-600 hover:underline text-xs"
                    onClick={() => setShiftTemplateFieldsRow(row)}
                  >
                    ערוך יחידות
                  </button>
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
                      value={currentSelection("shift_templates", row)}
                      onChange={(e) => setRowAction("shift_templates", row.row, e.target.value)}
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

Add the `shiftTemplateFieldsRow` state near the other modal-context state declarations:

```tsx
const [shiftTemplateFieldsRow, setShiftTemplateFieldsRow] = useState<ShiftTemplateRow | null>(null);
```

And its modal render, alongside the `dutyTypeFieldsRow`/`exemptionTypeFieldsRow` modals from Task 8:

```tsx
{shiftTemplateFieldsRow && (
  <ImportRowFieldsModal
    onClose={() => setShiftTemplateFieldsRow(null)}
    eligibleUnits={{
      value: shiftTemplateFieldsRow.resolved_eligible_node_ids,
      onChange: (next) => {
        setFieldOverride("shift_templates", shiftTemplateFieldsRow.row, "resolved_eligible_node_ids", next);
        setShiftTemplateFieldsRow({ ...shiftTemplateFieldsRow, resolved_eligible_node_ids: next });
      },
    }}
  />
)}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm test -- ImportSessionReviewPage -t "renders full shift_template detail"`
Expected: PASS.

- [ ] **Step 6: Run the full test file and typecheck**

Run: `npm test -- ImportSessionReviewPage && npm run typecheck`
Expected: all PASS, no type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/importSessions.ts frontend/src/pages/ImportSessionReviewPage.tsx frontend/src/pages/ImportSessionReviewPage.test.tsx
git commit -m "feat: full-detail, inline-editable shift_templates review tab"
```

---

### Task 14: Final verification pass

**Files:** none (verification only).

- [ ] **Step 1: Run the targeted backend test areas touched by this plan**

Run: `cd backend && pytest -m duty -q`
Expected: all PASS.

- [ ] **Step 2: Run the full (non-slow) backend suite**

Run: `cd backend && pytest -q`
Expected: all PASS.

- [ ] **Step 3: Run frontend lint, typecheck, and tests**

Run (from `frontend/`): `npm run lint && npm run typecheck && npm test`
Expected: zero lint warnings, no type errors, all tests PASS.

- [ ] **Step 4: Manual smoke test of the reconciled export round trip**

Using the dev stack (`./dev.ps1` from repo root): log in as admin, go to `/planning/export`, check "ייצוא נתוני מערכת", export, then upload the resulting file at `/import/upload`. Confirm the review page's soldiers/duty_shifts/assignments/shift_templates tabs show non-zero rows matching current DB state (all as `action: "update"`, since they already exist).

- [ ] **Step 5: Commit (if the smoke test surfaces any fixes)**

```bash
git add -A
git commit -m "fix: address issues found in final verification pass"
```

(Skip this step entirely if no fixes were needed.)
