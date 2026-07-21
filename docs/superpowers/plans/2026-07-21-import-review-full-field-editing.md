# Import Review Full Field-Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing `_field_overrides` inline-edit mechanism (currently only wired to `duty_types`/`exemption_types`/`shift_templates`) to all 8 import-review tabs, add combobox remap for `assignments`, add a generic row-detail/inspect modal, and round out the soldier import schema to the full `Soldier` profile field set.

**Architecture:** The backend already has a proven pattern in `_resolve_duty_types`/`_resolve_exemption_types`/`_resolve_shift_templates`: an `overrides: dict[str, dict] | None` parameter, a per-row `override = overrides.get(str(row.source_row), {})` lookup, and a local `field(name, default)` helper that reads the override first and falls back to the parsed value — all *before* the resolver's existing validation runs, so nothing is duplicated. This plan mechanically extends that same pattern to `_resolve_soldiers`, `_resolve_duty_locations`, `_resolve_hierarchy`, `_resolve_duty_shifts`, `_resolve_assignments`. `confirm_session` needs **no changes** for this override plumbing — it already reads whatever ends up in `parsed_state`, which already reflects the last reparse (confirmed by reading the existing duty_types/exemption_types/shift_templates code paths). The one exception is the new soldier profile fields (Task 7), which are genuinely new data the resolver has never emitted before, so `confirm_session`'s soldiers block needs new lines to persist them.

**Tech Stack:** FastAPI/SQLAlchemy backend (Python 3.12+), React/TypeScript frontend, pytest for backend tests, openpyxl for Excel parsing.

## Global Constraints

- Every backend resolver change follows the exact `overrides.get(str(row.source_row), {})` + `field(name, default)` pattern already used in `_resolve_duty_types` (`backend/app/services/import_sessions.py:294-385`) — do not invent a different mechanism.
- Every frontend inline-edit cell follows the exact `readOnly ? <span> : <input onBlur={setFieldOverride(...)}>` pattern already used in the duty_types/shift_templates tabs (`frontend/src/pages/ImportSessionReviewPage.tsx`).
- No changes to `confirm_session`'s control flow (skip/error/action handling) — only additive field reads, and only where genuinely new fields are introduced (Task 7).
- Hebrew UI strings for all new labels/columns, matching the existing tabs' style (`ACTION_LABEL`, column headers already in the file).
- All new backend params are optional with `None` defaults so existing callers (including tests) keep working unchanged.

---

## Task 1: `_resolve_duty_locations` — field-override support

**Files:**
- Modify: `backend/app/services/import_sessions.py:142-162`
- Test: `backend/app/services/tests/test_import_sessions_service.py`

**Interfaces:**
- Consumes: nothing new (no name-mapping deps for this resolver)
- Produces: `_resolve_duty_locations(session, data, overrides=None)` — later wired into `_resolve_and_score` in Task 6

- [ ] **Step 1: Write the failing test**

Add to `backend/app/services/tests/test_import_sessions_service.py` (near the other field-override tests, e.g. after `test_exemption_type_field_override_changes_resolved_flag`):

```python
def _wb_with_duty_locations(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("duty_locations")
    ws.append(["name", "base", "active"])
    for r in rows:
        ws.append(r)
    return wb


def test_duty_location_field_override_changes_base(admin_session):
    wb = _wb_with_duty_locations([
        [f"loc_{_uid()}", "Original Base", "true"],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row_num = sess.parsed_state["duty_locations"][0]["row"]

    set_selections(admin_session, session_id=sess.id, selections={
        "_field_overrides": {"duty_locations": {str(row_num): {"base": "Overridden Base"}}},
    })
    admin_session.commit()

    reparse_session(admin_session, session_id=sess.id, actor=admin)
    row = sess.parsed_state["duty_locations"][0]
    assert row["base"] == "Overridden Base"
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`, venv active): `pytest app/services/tests/test_import_sessions_service.py::test_duty_location_field_override_changes_base -v`
Expected: FAIL — `_resolve_duty_locations()` has no way to apply the override, so `row["base"]` stays `"Original Base"`.

- [ ] **Step 3: Write minimal implementation**

Replace `_resolve_duty_locations` in `backend/app/services/import_sessions.py:142-162`:

```python
def _resolve_duty_locations(
    session: Session,
    data: ParsedImportData,
    overrides: dict[str, dict] | None = None,
) -> list[dict]:
    overrides = overrides or {}
    existing_by_name = {
        loc.name: loc for loc in session.execute(select(DutyLocation)).scalars()
    }
    out = []
    for row in data.duty_locations:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        name = field("name", row.name)
        base = field("base", row.base)
        active = field("active", row.active)

        if not name:
            errors.append("חסר שם מיקום")
        existing = existing_by_name.get(name) if name else None
        action = "error" if errors else ("update" if existing else "new")
        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "name": name,
            "base": base,
            "active": active,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest app/services/tests/test_import_sessions_service.py::test_duty_location_field_override_changes_base -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/import_sessions.py backend/app/services/tests/test_import_sessions_service.py
git commit -m "feat: add field-override support to duty_locations import resolver"
```

---

## Task 2: `_resolve_hierarchy` — field-override support

**Files:**
- Modify: `backend/app/services/import_sessions.py:184-291`
- Test: `backend/app/services/tests/test_import_sessions_service.py`

**Interfaces:**
- Consumes: nothing new beyond its existing `node_by_name`/`node_by_row` params
- Produces: `_resolve_hierarchy(session, data, actor, node_by_name=None, node_by_row=None, overrides=None)` — wired in Task 6

- [ ] **Step 1: Write the failing test**

```python
def _wb_with_hierarchy(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("hierarchy")
    ws.append([
        "name", "level", "parent_name", "commander_personal_number",
        "commander_name", "duty_manager_refs",
    ])
    for r in rows:
        ws.append(r)
    return wb


def test_hierarchy_field_override_changes_level(admin_session):
    wb = _wb_with_hierarchy([
        [f"node_{_uid()}", "branch", "", "", "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row_num = sess.parsed_state["hierarchy"][0]["row"]

    set_selections(admin_session, session_id=sess.id, selections={
        "_field_overrides": {"hierarchy": {str(row_num): {"level": "team"}}},
    })
    admin_session.commit()

    reparse_session(admin_session, session_id=sess.id, actor=admin)
    row = sess.parsed_state["hierarchy"][0]
    assert row["level"] == "team"
```

(Verify `"team"` is a valid `HierarchyLevelType.key` seeded in the test DB by checking existing hierarchy tests in this file — e.g. `test_create_session_soldier_unresolved_hierarchy_node_errors` uses `create_node(admin_session, level="branch", ...)` elsewhere in the suite; if `"team"` isn't a seeded level key, use whatever second valid level string the existing `create_node` calls in this file already use, e.g. `"unit"`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest app/services/tests/test_import_sessions_service.py::test_hierarchy_field_override_changes_level -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Replace `_resolve_hierarchy` in `backend/app/services/import_sessions.py:184-291`, adding `overrides` handling. The body is unchanged except: add the parameter, add `overrides = overrides or {}`, add `override = overrides.get(str(row.source_row), {})` and a `field(name, default)` helper inside the loop, and route `name`/`level`/`parent_name`/`commander_personal_number`/`commander_name` through `field(...)` before they're used:

```python
def _resolve_hierarchy(
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
    existing_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}
    valid_levels = {
        lt.key for lt in session.execute(select(HierarchyLevelType)).scalars()
    }
    by_pn = {s.personal_number: s for s in session.execute(select(Soldier)).scalars()}
    by_name: dict[str, list[Soldier]] = {}
    for s in by_pn.values():
        by_name.setdefault(s.full_name, []).append(s)

    row_by_name = {row.name: row for row in data.hierarchy}

    out = []
    for row in data.hierarchy:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        name = field("name", row.name)
        level = field("level", row.level)
        parent_name = field("parent_name", row.parent_name)
        commander_personal_number = field("commander_personal_number", row.commander_personal_number)
        commander_name = field("commander_name", row.commander_name)

        if level not in valid_levels:
            errors.append(f"סוג יחידה לא מוכר '{level}'")

        existing = existing_by_name.get(name)

        resolved_parent_id = None
        if parent_name:
            row_key = f"hierarchy:{row.source_row}"
            mapped_id = node_by_row.get(row_key) or node_by_name.get(parent_name)
            if mapped_id:
                resolved_parent_id = mapped_id
            elif parent_name in existing_by_name:
                resolved_parent_id = str(existing_by_name[parent_name].id)
            elif parent_name in row_by_name:
                resolved_parent_id = None
            else:
                errors.append(f"יחידת אב לא מזוהה '{parent_name}'")

        resolved_commander_id = None
        if commander_personal_number or commander_name:
            soldier, err = _resolve_soldier_ref(
                commander_personal_number, commander_name, by_pn, by_name
            )
            if soldier is not None:
                resolved_commander_id = str(soldier.id)
            else:
                errors.append(f"מפקד לא מזוהה: {err}")

        dm_results = []
        for ref in row.duty_manager_refs:
            pn, _, ref_name = ref.partition(":")
            soldier, err = _resolve_soldier_ref(pn.strip(), ref_name.strip(), by_pn, by_name)
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
        elif action == "new" and actor.role != "admin" and not resolved_parent_id:
            action = "out_of_scope"

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "name": name,
            "level": level,
            "parent_name": parent_name,
            "resolved_parent_id": resolved_parent_id,
            "commander_personal_number": commander_personal_number,
            "commander_name": commander_name,
            "resolved_commander_id": resolved_commander_id,
            "duty_manager_refs": dm_results,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest app/services/tests/test_import_sessions_service.py::test_hierarchy_field_override_changes_level -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/import_sessions.py backend/app/services/tests/test_import_sessions_service.py
git commit -m "feat: add field-override support to hierarchy import resolver"
```

---

## Task 3: `_resolve_soldiers` — field-override support for existing fields

**Files:**
- Modify: `backend/app/services/import_sessions.py:50-139`
- Test: `backend/app/services/tests/test_import_sessions_service.py`

**Interfaces:**
- Consumes: nothing new beyond existing `node_by_name`/`node_by_row`
- Produces: `_resolve_soldiers(session, data, actor, node_by_name=None, node_by_row=None, overrides=None)` — wired in Task 6

- [ ] **Step 1: Write the failing test**

```python
def test_soldier_field_override_changes_rank(admin_session):
    wb = _wb_with_soldiers([
        ["1234567", "Some Soldier", "rank1", "", "", "", "", "", "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row_num = sess.parsed_state["soldiers"][0]["row"]

    set_selections(admin_session, session_id=sess.id, selections={
        "_field_overrides": {"soldiers": {str(row_num): {"rank": "rank2"}}},
    })
    admin_session.commit()

    reparse_session(admin_session, session_id=sess.id, actor=admin)
    row = sess.parsed_state["soldiers"][0]
    assert row["rank"] == "rank2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest app/services/tests/test_import_sessions_service.py::test_soldier_field_override_changes_rank -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Replace `_resolve_soldiers` in `backend/app/services/import_sessions.py:50-139`:

```python
def _resolve_soldiers(
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
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        personal_number = field("personal_number", row.personal_number)
        full_name = field("full_name", row.full_name)
        rank = field("rank", row.rank)
        gender = field("gender", row.gender)
        is_officer = field("is_officer", row.is_officer)
        hierarchy_node_name = field("hierarchy_node_name", row.hierarchy_node_name)
        enrolled_at = field("enrolled_at", row.enrolled_at)
        enlistment_date = field("enlistment_date", row.enlistment_date)
        phone = field("phone", row.phone)
        email = field("email", row.email)

        if not personal_number:
            errors.append("חסר מספר אישי")
        if not full_name:
            errors.append("חסר שם מלא")

        node = None
        if hierarchy_node_name:
            row_key = f"soldiers:{row.source_row}"
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

        existing = existing_by_pn.get(personal_number) if personal_number else None
        if existing is None and personal_number and full_name:
            candidates = existing_by_full_name.get(full_name, [])
            if len(candidates) == 1:
                existing = candidates[0]
                warnings.append(
                    f"נמצא לפי שם — מספר אישי עודכן מ-'{existing.personal_number}' ל-'{personal_number}'"
                )
            elif len(candidates) > 1:
                errors.append(
                    f"שם '{full_name}' אינו חד משמעי (מספר אישי '{personal_number}' לא נמצא)"
                )

        if errors:
            action = "error"
        elif existing is not None:
            action = "update"
        else:
            action = "new"

        if action != "error" and node is not None:
            if actor.role != "admin" and not is_node_in_actor_scope(
                session=session, actor=actor, node_id=node.id
            ):
                action = "out_of_scope"

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "warnings": warnings,
            "personal_number": personal_number,
            "full_name": full_name,
            "rank": rank,
            "gender": gender,
            "is_officer": is_officer,
            "hierarchy_node_id": str(node.id) if node is not None else None,
            "hierarchy_node_name": hierarchy_node_name,
            "enrolled_at": enrolled_at,
            "enlistment_date": enlistment_date,
            "phone": phone,
            "email": email,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest app/services/tests/test_import_sessions_service.py::test_soldier_field_override_changes_rank -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/import_sessions.py backend/app/services/tests/test_import_sessions_service.py
git commit -m "feat: add field-override support to soldiers import resolver"
```

---

## Task 4: `_resolve_duty_shifts` — field-override support

**Files:**
- Modify: `backend/app/services/import_sessions.py:461-562`
- Test: `backend/app/services/tests/test_import_sessions_service.py`

**Interfaces:**
- Consumes: nothing new beyond existing `dt_by_name`/`dt_by_row`/`node_by_name`/`node_by_row`
- Produces: `_resolve_duty_shifts(session, data, actor, dt_by_name=None, dt_by_row=None, node_by_name=None, node_by_row=None, overrides=None)` — wired in Task 6

- [ ] **Step 1: Write the failing test**

```python
def test_duty_shift_field_override_changes_required_count(admin_session):
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    admin_session.commit()

    wb = _wb_with_duty_shifts([
        [dt.name, loc.name, "15.06.2024", "16.06.2024", "", "", 5, "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row_num = sess.parsed_state["duty_shifts"][0]["row"]

    set_selections(admin_session, session_id=sess.id, selections={
        "_field_overrides": {"duty_shifts": {str(row_num): {"required_count": 9}}},
    })
    admin_session.commit()

    reparse_session(admin_session, session_id=sess.id, actor=admin)
    row = sess.parsed_state["duty_shifts"][0]
    assert row["required_count"] == 9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest app/services/tests/test_import_sessions_service.py::test_duty_shift_field_override_changes_required_count -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Replace `_resolve_duty_shifts` in `backend/app/services/import_sessions.py:461-562`:

```python
def _resolve_duty_shifts(
    session: Session,
    data: ParsedImportData,
    actor: Soldier,
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

    out = []
    for row in data.duty_shifts:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        duty_type_name = field("duty_type_name", row.duty_type_name)
        duty_location_name = field("duty_location_name", row.duty_location_name)
        start_date = field("start_date", row.start_date)
        end_date = field("end_date", row.end_date)
        start_time = field("start_time", row.start_time)
        end_time = field("end_time", row.end_time)
        required_count = field("required_count", row.required_count)
        notes = field("notes", row.notes)

        duty_type = None
        if duty_type_name:
            row_key = f"duty_shifts:{row.source_row}"
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

        if not start_date:
            errors.append("חסר תאריך התחלה")
        if not end_date:
            errors.append("חסר תאריך סיום")

        quota_dicts = []
        quota_total = 0
        for q in row.node_quotas:
            quota_key = f"duty_shifts:{row.source_row}:{q.node_name}"
            mapped_node_id = node_by_row.get(quota_key) or node_by_name.get(q.node_name)
            node = None
            if mapped_node_id:
                try:
                    node = session.get(HierarchyNode, uuid.UUID(mapped_node_id))
                except ValueError:
                    pass
            if node is None:
                node = nodes_by_name.get(q.node_name)
            quota_dicts.append({
                "node_name": q.node_name,
                "node_id": str(node.id) if node is not None else None,
                "count": q.count,
                "resolved": node is not None,
            })
            quota_total += q.count

        if quota_total > required_count:
            errors.append(
                f"סה\"כ מכסות ({quota_total}) גדול מהכמות הנדרשת ({required_count})"
            )

        action = "error" if errors else "new"

        if action == "new" and actor.role != "admin":
            resolved_node_ids = [
                uuid.UUID(qd["node_id"]) for qd in quota_dicts if qd["resolved"]
            ]
            for node_id in resolved_node_ids:
                if not is_node_in_actor_scope(session=session, actor=actor, node_id=node_id):
                    action = "out_of_scope"
                    break

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "duty_type_name": duty_type_name,
            "resolved_duty_type_id": str(duty_type.id) if duty_type is not None else None,
            "duty_location_name": duty_location_name,
            "resolved_duty_location_id": str(location.id) if location is not None else None,
            "start_date": start_date,
            "end_date": end_date,
            "start_time": start_time,
            "end_time": end_time,
            "required_count": required_count,
            "node_quotas": quota_dicts,
            "notes": notes,
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest app/services/tests/test_import_sessions_service.py::test_duty_shift_field_override_changes_required_count -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/import_sessions.py backend/app/services/tests/test_import_sessions_service.py
git commit -m "feat: add field-override support to duty_shifts import resolver"
```

---

## Task 5: `_resolve_assignments` — field-override support + duty_type_name remap

**Files:**
- Modify: `backend/app/services/import_sessions.py:669-819`
- Test: `backend/app/services/tests/test_import_sessions_service.py`

**Interfaces:**
- Consumes: `dt_by_name: dict[str, str]`, `dt_by_row: dict[str, str]` (same maps `_resolve_duty_shifts` already receives, built from `_name_mappings.duty_type` in `_resolve_and_score`)
- Produces: `_resolve_assignments(session, data, actor, resolved_duty_shifts, dt_by_name=None, dt_by_row=None, overrides=None)` — wired in Task 6

- [ ] **Step 1: Write the failing tests**

Two tests: one for scalar override, one for the new duty_type remap.

```python
def test_assignment_field_override_changes_notes(admin_session):
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    soldier = create_soldier(admin_session, personal_number=f"sld_{_uid()}", full_name="Assignee")
    admin_session.commit()

    from app.db.models import DutyShift
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_type(2024, 6, 15), end_date=date_type(2024, 6, 16),
        required_count=5,
    )
    admin_session.add(shift)
    admin_session.commit()

    wb = _wb_with_assignments([
        [soldier.personal_number, soldier.full_name, dt.name, loc.name,
         "15.06.2024", "16.06.2024", "", "", "false", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row_num = sess.parsed_state["assignments"][0]["row"]

    set_selections(admin_session, session_id=sess.id, selections={
        "_field_overrides": {"assignments": {str(row_num): {"notes": "overridden note"}}},
    })
    admin_session.commit()

    reparse_session(admin_session, session_id=sess.id, actor=admin)
    row = sess.parsed_state["assignments"][0]
    assert row["notes"] == "overridden note"


def test_assignment_duty_type_resolved_via_by_row_mapping(admin_session):
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    soldier = create_soldier(admin_session, personal_number=f"sld_{_uid()}", full_name="Assignee")
    admin_session.commit()

    from app.db.models import DutyShift
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_type(2024, 6, 15), end_date=date_type(2024, 6, 16),
        required_count=5,
    )
    admin_session.add(shift)
    admin_session.commit()

    wb = _wb_with_assignments([
        [soldier.personal_number, soldier.full_name, "no_such_duty_type", loc.name,
         "15.06.2024", "16.06.2024", "", "", "false", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row_num = sess.parsed_state["assignments"][0]["row"]
    assert sess.parsed_state["assignments"][0]["action"] == "error"

    set_selections(admin_session, session_id=sess.id, selections={
        "_name_mappings": {"duty_type": {"by_row": {f"assignments:{row_num}": str(dt.id)}}},
    })
    admin_session.commit()

    reparse_session(admin_session, session_id=sess.id, actor=admin)
    row = sess.parsed_state["assignments"][0]
    assert row["action"] == "new"
```

(`_wb_with_assignments` already exists in this test file at line 643 — reuse it, don't redefine.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest app/services/tests/test_import_sessions_service.py::test_assignment_field_override_changes_notes app/services/tests/test_import_sessions_service.py::test_assignment_duty_type_resolved_via_by_row_mapping -v`
Expected: FAIL — `_resolve_assignments` currently ignores overrides entirely and has no duty_type remap path (an unmatched name always stays an error since there is no `dt_by_name`/`dt_by_row` param to consult).

- [ ] **Step 3: Write minimal implementation**

Replace `_resolve_assignments` in `backend/app/services/import_sessions.py:669-819` (the full function, from its `def` through its final `return out`):

```python
def _resolve_assignments(
    session: Session,
    data: ParsedImportData,
    actor: Soldier,
    resolved_duty_shifts: list[dict],
    dt_by_name: dict[str, str] | None = None,
    dt_by_row: dict[str, str] | None = None,
    overrides: dict[str, dict] | None = None,
) -> list[dict]:
    dt_by_name = dt_by_name or {}
    dt_by_row = dt_by_row or {}
    overrides = overrides or {}

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
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        personal_number = field("personal_number", row.personal_number)
        full_name = field("full_name", row.full_name)
        duty_type_name = field("duty_type_name", row.duty_type_name)
        duty_location_name = field("duty_location_name", row.duty_location_name)
        start_date = field("start_date", row.start_date)
        end_date = field("end_date", row.end_date)
        start_time = field("start_time", row.start_time)
        end_time = field("end_time", row.end_time)
        is_reserve = field("is_reserve", row.is_reserve)
        notes = field("notes", row.notes)

        soldier = soldiers_by_pn.get(personal_number) if personal_number else None
        if soldier is not None:
            if soldier.full_name != full_name:
                errors.append(
                    f"שם מלא '{full_name}' אינו תואם לחייל עם מספר אישי "
                    f"'{personal_number}' ('{soldier.full_name}')"
                )
        else:
            candidates = soldiers_by_full_name.get(full_name, []) if full_name else []
            if len(candidates) == 1:
                soldier = candidates[0]
                warnings.append(f"נמצא לפי שם — מספר אישי '{personal_number}' לא נמצא")
            elif len(candidates) > 1:
                errors.append(
                    f"מספר אישי '{personal_number}' לא נמצא ושם '{full_name}' אינו חד משמעי"
                )
            else:
                errors.append(
                    f"לא נמצא חייל עם מספר אישי '{personal_number}' או שם '{full_name}'"
                )

        duty_type = None
        if duty_type_name:
            row_key = f"assignments:{row.source_row}"
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

        resolved_duty_shift_id: str | None = None
        matched_session_row: int | None = None
        shift_key_str: str | None = None
        required_count: int | None = None
        if duty_type is not None and location is not None and start_date and end_date:
            key = (
                duty_type.id, location.id, start_date, end_date,
                _default_time(start_time, "00:00"),
                _default_time(end_time, "23:59"),
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
            "personal_number": personal_number,
            "full_name": full_name,
            "duty_type_name": duty_type_name,
            "duty_location_name": duty_location_name,
            "start_date": start_date,
            "end_date": end_date,
            "start_time": start_time,
            "end_time": end_time,
            "is_reserve": is_reserve,
            "notes": notes,
            "resolved_soldier_id": str(soldier.id) if soldier is not None else None,
            "resolved_duty_shift_id": resolved_duty_shift_id,
            "matched_session_row": matched_session_row,
        })
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest app/services/tests/test_import_sessions_service.py::test_assignment_field_override_changes_notes app/services/tests/test_import_sessions_service.py::test_assignment_duty_type_resolved_via_by_row_mapping -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/import_sessions.py backend/app/services/tests/test_import_sessions_service.py
git commit -m "feat: add field-override support and duty_type remap to assignments import resolver"
```

---

## Task 6: Wire all five resolvers into `_resolve_and_score`

**Files:**
- Modify: `backend/app/services/import_sessions.py:822-848`
- Test: `backend/app/services/tests/test_import_sessions_service.py` (covered by Tasks 1-5's tests, which exercise this wiring already — no new test needed, but re-run the full override suite as a regression check)

**Interfaces:**
- Consumes: all five resolver signatures from Tasks 1-5
- Produces: `_resolve_and_score` unchanged signature, now passing overrides/mappings through to every group

- [ ] **Step 1: Run the existing override tests first (should already fail without this wiring)**

Run: `pytest app/services/tests/test_import_sessions_service.py -k "field_override or by_row_mapping" -v`
Expected: the five new tests from Tasks 1-5 currently FAIL (resolvers support overrides but `_resolve_and_score` doesn't pass them yet).

- [ ] **Step 2: Wire the overrides through**

Replace `_resolve_and_score` in `backend/app/services/import_sessions.py:822-848`:

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
    duty_shifts = _resolve_duty_shifts(
        session, data, actor, dt_by_name, dt_by_row, node_by_name, node_by_row,
        fo.get("duty_shifts", {}),
    )
    return {
        "soldiers": _resolve_soldiers(
            session, data, actor, node_by_name, node_by_row, fo.get("soldiers", {}),
        ),
        "duty_shifts": duty_shifts,
        "shift_templates": _resolve_shift_templates(
            session, data, dt_by_name, dt_by_row, node_by_name, node_by_row, fo.get("shift_templates", {})
        ),
        "assignments": _resolve_assignments(
            session, data, actor, duty_shifts, dt_by_name, dt_by_row, fo.get("assignments", {}),
        ),
        "duty_locations": _resolve_duty_locations(session, data, fo.get("duty_locations", {})),
        "hierarchy": _resolve_hierarchy(
            session, data, actor, node_by_name, node_by_row, fo.get("hierarchy", {}),
        ),
        "duty_types": _resolve_duty_types(session, data, node_by_name, node_by_row, fo.get("duty_types", {})),
        "exemption_types": _resolve_exemption_types(session, data, dt_by_name, dt_by_row, fo.get("exemption_types", {})),
        "parser_id": data.parser_id,
        "parser_warnings": data.parser_warnings,
    }
```

- [ ] **Step 3: Run the full override test set to verify all pass**

Run: `pytest app/services/tests/test_import_sessions_service.py -k "field_override or by_row_mapping" -v`
Expected: PASS (all tests from Tasks 1, 2, 3, 4, 5, plus every pre-existing duty_types/exemption_types/shift_templates override test)

- [ ] **Step 4: Run the entire import-sessions test file to check for regressions**

Run: `pytest app/services/tests/test_import_sessions_service.py -v`
Expected: PASS — every test in the file, including the pre-existing assignment/hierarchy/soldier resolution tests that don't use overrides at all (they call the resolvers with `overrides=None`, which is the same as before).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/import_sessions.py
git commit -m "feat: wire field-override support through _resolve_and_score for all import groups"
```

---

## Task 7: Soldier profile field parity (backend)

**Files:**
- Modify: `backend/app/services/import_parsers/schema.py` (`ImportSoldierRow`)
- Modify: `backend/app/services/import_parsers/v1_standard.py` (soldiers sheet reader, ~line 150-165)
- Modify: `backend/app/services/import_sessions.py` (`_resolve_soldiers` output dict; `confirm_session`'s soldiers `new`/`update` branches, ~lines 941-990)
- Test: `backend/app/services/tests/test_import_sessions_service.py`

**Interfaces:**
- Consumes: `_parse_bool`, `_parse_date` helpers already imported in `v1_standard.py` from `app.services.import_parsers._shared_parsing`
- Produces: `ImportSoldierRow` with 10 new optional fields; `_resolve_soldiers` output dict carries them through (no validation beyond parse-time, matching existing `phone`/`email` precedent); `confirm_session` persists them on both create and update

- [ ] **Step 1: Write the failing test**

```python
def _wb_with_soldiers_full_profile(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("soldiers")
    ws.append([
        "personal_number", "full_name", "rank", "gender", "is_officer",
        "hierarchy_node_name", "enrolled_at", "enlistment_date", "phone", "email",
        "is_career", "next_rank_date", "bahad1_graduate",
        "has_military_driving_license", "military_driving_license_expiry",
        "mandatory_end_date", "discharge_date", "last_mitvahim_date",
        "last_alal_date", "left_at",
    ])
    for r in rows:
        ws.append(r)
    return wb


def test_soldier_import_round_trips_full_profile_fields(admin_session):
    wb = _wb_with_soldiers_full_profile([
        [
            "1234567", "Some Soldier", "", "", "",
            "", "", "", "", "",
            "true", "01.01.2027", "true",
            "true", "01.01.2028",
            "01.01.2026", "", "",
            "", "",
        ],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )

    row = sess.parsed_state["soldiers"][0]
    assert row["is_career"] is True
    assert row["next_rank_date"] == "2027-01-01"
    assert row["bahad1_graduate"] is True
    assert row["has_military_driving_license"] is True
    assert row["military_driving_license_expiry"] == "2028-01-01"
    assert row["mandatory_end_date"] == "2026-01-01"

    confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    created = admin_session.execute(
        select(Soldier).where(Soldier.personal_number == "1234567")
    ).scalar_one()
    assert created.is_career is True
    assert created.next_rank_date == date_type(2027, 1, 1)
    assert created.bahad1_graduate is True
    assert created.has_military_driving_license is True
    assert created.military_driving_license_expiry == date_type(2028, 1, 1)
    assert created.mandatory_end_date == date_type(2026, 1, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest app/services/tests/test_import_sessions_service.py::test_soldier_import_round_trips_full_profile_fields -v`
Expected: FAIL — `ImportSoldierRow` has no such fields yet (Pydantic will silently ignore unknown Excel columns since `_sheet_rows` just builds a dict; the row object won't carry the values at all, so `row["is_career"]` will `KeyError`/assert `None is True` failure).

- [ ] **Step 3: Write minimal implementation**

**3a.** In `backend/app/services/import_parsers/schema.py`, extend `ImportSoldierRow`:

```python
class ImportSoldierRow(BaseModel):
    source_row: int
    personal_number: str
    full_name: str
    rank: str | None = None
    gender: str | None = None
    is_officer: bool | None = None
    hierarchy_node_name: str | None = None
    enrolled_at: str | None = None
    enlistment_date: str | None = None
    phone: str | None = None
    email: str | None = None
    is_career: bool | None = None
    next_rank_date: str | None = None
    bahad1_graduate: bool | None = None
    has_military_driving_license: bool | None = None
    military_driving_license_expiry: str | None = None
    mandatory_end_date: str | None = None
    discharge_date: str | None = None
    last_mitvahim_date: str | None = None
    last_alal_date: str | None = None
    left_at: str | None = None
```

**3b.** In `backend/app/services/import_parsers/v1_standard.py`, extend the soldiers-sheet comprehension (replacing lines ~150-165):

```python
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
                is_career=_parse_bool(r.get("is_career")),
                next_rank_date=_parse_date(r.get("next_rank_date")),
                bahad1_graduate=_parse_bool(r.get("bahad1_graduate")),
                has_military_driving_license=_parse_bool(r.get("has_military_driving_license")),
                military_driving_license_expiry=_parse_date(r.get("military_driving_license_expiry")),
                mandatory_end_date=_parse_date(r.get("mandatory_end_date")),
                discharge_date=_parse_date(r.get("discharge_date")),
                last_mitvahim_date=_parse_date(r.get("last_mitvahim_date")),
                last_alal_date=_parse_date(r.get("last_alal_date")),
                left_at=_parse_date(r.get("left_at")),
            )
            for r in _sheet_rows(wb, "soldiers")
        ]
```

**3c.** In `backend/app/services/import_sessions.py`, `_resolve_soldiers` (as rewritten in Task 3): add the 10 new fields through the same `field(name, default)` helper and into the output dict. Extend the `field(...)` calls block:

```python
        is_career = field("is_career", row.is_career)
        next_rank_date = field("next_rank_date", row.next_rank_date)
        bahad1_graduate = field("bahad1_graduate", row.bahad1_graduate)
        has_military_driving_license = field("has_military_driving_license", row.has_military_driving_license)
        military_driving_license_expiry = field("military_driving_license_expiry", row.military_driving_license_expiry)
        mandatory_end_date = field("mandatory_end_date", row.mandatory_end_date)
        discharge_date = field("discharge_date", row.discharge_date)
        last_mitvahim_date = field("last_mitvahim_date", row.last_mitvahim_date)
        last_alal_date = field("last_alal_date", row.last_alal_date)
        left_at = field("left_at", row.left_at)
```

and extend the output dict (appended after `"email": email,`):

```python
            "is_career": is_career,
            "next_rank_date": next_rank_date,
            "bahad1_graduate": bahad1_graduate,
            "has_military_driving_license": has_military_driving_license,
            "military_driving_license_expiry": military_driving_license_expiry,
            "mandatory_end_date": mandatory_end_date,
            "discharge_date": discharge_date,
            "last_mitvahim_date": last_mitvahim_date,
            "last_alal_date": last_alal_date,
            "left_at": left_at,
```

**3d.** In `confirm_session`'s soldiers block (`backend/app/services/import_sessions.py:934-994`), extend the `new` branch's `Soldier(...)` constructor call and the date-field assignments that follow it:

```python
            if effective == "new":
                new_soldier = Soldier(
                    personal_number=row["personal_number"],
                    full_name=row["full_name"],
                    password_hash=hash_password(secrets.token_hex(16)),
                    must_change_password=True,
                    rank=row.get("rank"),
                    gender=row.get("gender"),
                    is_officer=row.get("is_officer"),
                    hierarchy_node_id=(
                        uuid.UUID(row["hierarchy_node_id"])
                        if row.get("hierarchy_node_id")
                        else None
                    ),
                    phone=row.get("phone"),
                    email=row.get("email"),
                    is_career=row.get("is_career") or False,
                    bahad1_graduate=row.get("bahad1_graduate") or False,
                    has_military_driving_license=row.get("has_military_driving_license"),
                )
                if row.get("enrolled_at"):
                    new_soldier.enrolled_at = date_type.fromisoformat(row["enrolled_at"])
                if row.get("enlistment_date"):
                    new_soldier.enlistment_date = date_type.fromisoformat(row["enlistment_date"])
                if row.get("next_rank_date"):
                    new_soldier.next_rank_date = date_type.fromisoformat(row["next_rank_date"])
                if row.get("military_driving_license_expiry"):
                    new_soldier.military_driving_license_expiry = date_type.fromisoformat(
                        row["military_driving_license_expiry"]
                    )
                if row.get("mandatory_end_date"):
                    new_soldier.mandatory_end_date = date_type.fromisoformat(row["mandatory_end_date"])
                if row.get("discharge_date"):
                    new_soldier.discharge_date = date_type.fromisoformat(row["discharge_date"])
                if row.get("last_mitvahim_date"):
                    new_soldier.last_mitvahim_date = date_type.fromisoformat(row["last_mitvahim_date"])
                if row.get("last_alal_date"):
                    new_soldier.last_alal_date = date_type.fromisoformat(row["last_alal_date"])
                if row.get("left_at"):
                    new_soldier.left_at = date_type.fromisoformat(row["left_at"])
                session.add(new_soldier)
                session.flush()
                created += 1
                created_soldiers.append(str(new_soldier.id))
            elif effective == "update" and row.get("existing_id"):
                s = session.get(Soldier, uuid.UUID(row["existing_id"]))
                if s is not None:
                    s.personal_number = row["personal_number"]
                    s.full_name = row["full_name"]
                    if row.get("rank") is not None:
                        s.rank = row["rank"]
                    if row.get("gender") is not None:
                        s.gender = row["gender"]
                    if row.get("is_officer") is not None:
                        s.is_officer = row["is_officer"]
                    if row.get("hierarchy_node_id") is not None:
                        s.hierarchy_node_id = uuid.UUID(row["hierarchy_node_id"])
                    if row.get("phone") is not None:
                        s.phone = row["phone"]
                    if row.get("email") is not None:
                        s.email = row["email"]
                    if row.get("is_career") is not None:
                        s.is_career = row["is_career"]
                    if row.get("bahad1_graduate") is not None:
                        s.bahad1_graduate = row["bahad1_graduate"]
                    if row.get("has_military_driving_license") is not None:
                        s.has_military_driving_license = row["has_military_driving_license"]
                    if row.get("enrolled_at"):
                        s.enrolled_at = date_type.fromisoformat(row["enrolled_at"])
                    if row.get("enlistment_date"):
                        s.enlistment_date = date_type.fromisoformat(row["enlistment_date"])
                    if row.get("next_rank_date"):
                        s.next_rank_date = date_type.fromisoformat(row["next_rank_date"])
                    if row.get("military_driving_license_expiry"):
                        s.military_driving_license_expiry = date_type.fromisoformat(
                            row["military_driving_license_expiry"]
                        )
                    if row.get("mandatory_end_date"):
                        s.mandatory_end_date = date_type.fromisoformat(row["mandatory_end_date"])
                    if row.get("discharge_date"):
                        s.discharge_date = date_type.fromisoformat(row["discharge_date"])
                    if row.get("last_mitvahim_date"):
                        s.last_mitvahim_date = date_type.fromisoformat(row["last_mitvahim_date"])
                    if row.get("last_alal_date"):
                        s.last_alal_date = date_type.fromisoformat(row["last_alal_date"])
                    if row.get("left_at"):
                        s.left_at = date_type.fromisoformat(row["left_at"])
                    session.flush()
                    updated += 1
                    created_soldiers.append(str(s.id))
                else:
                    skipped += 1
            else:
                skipped += 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest app/services/tests/test_import_sessions_service.py::test_soldier_import_round_trips_full_profile_fields -v`
Expected: PASS

- [ ] **Step 5: Run the full backend test suite for regressions**

Run (from `backend/`): `pytest -q`
Expected: PASS (fast suite, ~1.5 min per `CLAUDE.md`)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/import_parsers/schema.py backend/app/services/import_parsers/v1_standard.py backend/app/services/import_sessions.py backend/app/services/tests/test_import_sessions_service.py
git commit -m "feat: round out soldier import schema to full Soldier profile field set"
```

---

## Task 8: Frontend — widen `setFieldOverride` + duty_locations tab inline edit

**Files:**
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`

**Interfaces:**
- Consumes: `DutyLocationRow` (already has `name`, `base`, `active`, `existing_id` — no `api/importSessions.ts` change needed)
- Produces: `setFieldOverride(group: string, row: number, field: string, value: unknown)` — widened signature every later frontend task relies on

- [ ] **Step 1: Widen `setFieldOverride`'s group parameter**

In `frontend/src/pages/ImportSessionReviewPage.tsx`, change:

```ts
  function setFieldOverride(
    group: "duty_types" | "exemption_types" | "shift_templates",
    row: number,
    field: string,
    value: unknown,
  ) {
```

to:

```ts
  function setFieldOverride(
    group: string,
    row: number,
    field: string,
    value: unknown,
  ) {
```

(No other change needed in the function body — it already only uses `group` as a string dict key.)

- [ ] **Step 2: Replace the duty_locations tab body**

Replace the `{tab === "duty_locations" && (...)}` block (currently rendering `name`, `base` as plain text) with inline-editable cells:

```tsx
        {tab === "duty_locations" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">שם</th>
                  <th className="text-right p-3">בסיס</th>
                  <th className="text-right p-3">פעיל</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {duty_locations.map((row: DutyLocationRow) => {
                  const canToggle = row.action !== "error" && row.action !== "out_of_scope";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">
                        {readOnly ? row.name : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.name}
                            onBlur={(e) => setFieldOverride("duty_locations", row.row, "name", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.base ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.base ?? ""}
                            onBlur={(e) => setFieldOverride("duty_locations", row.row, "base", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? (row.active === null ? "—" : row.active ? "כן" : "לא") : (
                          <input
                            type="checkbox"
                            checked={row.active ?? false}
                            onChange={(e) => setFieldOverride("duty_locations", row.row, "active", e.target.checked)}
                          />
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
```

- [ ] **Step 3: Type-check**

Run (from `frontend/`): `npm run typecheck`
Expected: no new errors.

- [ ] **Step 4: Manual verification**

Start the dev stack (`.\dev.ps1` from repo root), upload an Excel file with a `duty_locations` sheet, open the review page, confirm the `base` field and `active` checkbox are editable and the value persists after navigating away and back (i.e. `setFieldOverride` → debounced save → reparse round-trip works).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ImportSessionReviewPage.tsx
git commit -m "feat: widen setFieldOverride and add inline edit to duty_locations import tab"
```

---

## Task 9: Frontend — hierarchy tab inline edit

**Files:**
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`

**Interfaces:**
- Consumes: `HierarchyImportRow` (already has `name`, `level` typed)
- Produces: nothing new consumed by later tasks

- [ ] **Step 1: Replace the hierarchy tab's `name`/`level`/`parent_name` cells**

In the `{tab === "hierarchy" && (...)}` block, replace the `name` and add a `level` inline-edit cell (parent/commander/duty_manager_refs stay exactly as they are today — unchanged):

```tsx
                      <td className="p-3">
                        {readOnly ? row.name : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.name}
                            onBlur={(e) => setFieldOverride("hierarchy", row.row, "name", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.level : (
                          <input
                            className="border rounded p-1 text-sm w-24 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.level}
                            onBlur={(e) => setFieldOverride("hierarchy", row.row, "level", e.target.value)}
                          />
                        )}
                      </td>
```

(These two `<td>` replace the existing `<td className="p-3">{row.name}</td>` and `<td className="p-3">{row.level}</td>` cells; the `parent_name`/commander/duty_manager_refs cells that follow are untouched.)

- [ ] **Step 2: Type-check**

Run: `npm run typecheck`
Expected: no new errors.

- [ ] **Step 3: Manual verification**

Upload a file with a `hierarchy` sheet, confirm `name`/`level` are editable inline and edits survive the debounced-save/reparse round trip (e.g. editing `level` to an invalid value should surface the existing "סוג יחידה לא מוכר" error from Task 2's resolver change).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ImportSessionReviewPage.tsx
git commit -m "feat: add inline edit to hierarchy import tab (name, level)"
```

---

## Task 10: Frontend — soldiers tab inline edit (existing fields)

**Files:**
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`

**Interfaces:**
- Consumes: `SoldierRow` (existing fields only — `full_name`, `rank`, `gender`, `is_officer`, `enlistment_date`, `phone`, `email`; the 10 new profile fields are handled in Task 15 via the detail modal, not as table columns)
- Produces: nothing new consumed by later tasks

- [ ] **Step 1: Replace the soldiers tab's `full_name` cell and add new columns**

The soldiers tab currently only shows `full_name`, `personal_number`, `hierarchy_node`, status. Add new columns for `rank`, `gender`, `is_officer`, `phone`, `email`, `enlistment_date` (personal_number stays read-only display — it's shown but not made a new editable column here since it isn't in scope per the resolver already reading it via `field()`; if desired later it's already override-capable from Task 3, but adding it as a column isn't required by this task). Replace the soldiers tab's `<thead>` and row cells:

```tsx
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">שם</th>
                  <th className="text-right p-3">מ&quot;א</th>
                  <th className="text-right p-3">דרגה</th>
                  <th className="text-right p-3">מגדר</th>
                  <th className="text-right p-3">קצין</th>
                  <th className="text-right p-3">טלפון</th>
                  <th className="text-right p-3">אימייל</th>
                  <th className="text-right p-3">תאריך גיוס</th>
                  <th className="text-right p-3">יחידה</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
```

and, in `<tbody>`, replace the first `<td className="p-3">{row.full_name}</td>` cell and insert the new cells right after the personal_number cell and before the hierarchy-node cell:

```tsx
                      <td className="p-3">
                        {readOnly ? row.full_name : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.full_name}
                            onBlur={(e) => setFieldOverride("soldiers", row.row, "full_name", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">{row.personal_number}</td>
                      <td className="p-3">
                        {readOnly ? row.rank ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-20 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.rank ?? ""}
                            onBlur={(e) => setFieldOverride("soldiers", row.row, "rank", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.gender ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.gender ?? ""}
                            onBlur={(e) => setFieldOverride("soldiers", row.row, "gender", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? (row.is_officer === null ? "—" : row.is_officer ? "כן" : "לא") : (
                          <input
                            type="checkbox"
                            checked={row.is_officer ?? false}
                            onChange={(e) => setFieldOverride("soldiers", row.row, "is_officer", e.target.checked)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.phone ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-28 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.phone ?? ""}
                            onBlur={(e) => setFieldOverride("soldiers", row.row, "phone", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.email ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.email ?? ""}
                            onBlur={(e) => setFieldOverride("soldiers", row.row, "email", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.enlistment_date ?? "—" : (
                          <input
                            type="date"
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.enlistment_date ?? ""}
                            onBlur={(e) => setFieldOverride("soldiers", row.row, "enlistment_date", e.target.value || null)}
                          />
                        )}
                      </td>
```

(The existing `hierarchy_node` cell with its combobox/remap logic follows unchanged, then the existing `StatusChip` cell, then the existing action-select cell.)

- [ ] **Step 2: Type-check**

Run: `npm run typecheck`
Expected: no new errors.

- [ ] **Step 3: Manual verification**

Upload a soldiers sheet, confirm rank/gender/is_officer/phone/email/enlistment_date are all editable inline and the row still correctly shows the hierarchy-node combobox when unresolved.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ImportSessionReviewPage.tsx
git commit -m "feat: add inline edit to soldiers import tab (existing profile fields)"
```

---

## Task 11: Frontend — duty_shifts tab inline edit

**Files:**
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`

**Interfaces:**
- Consumes: `DutyShiftRow` (already has `start_date`, `end_date`, `start_time`, `end_time`, `required_count`, `notes` typed)
- Produces: nothing new consumed by later tasks

- [ ] **Step 1: Replace the duty_shifts tab's date/count cells and add a notes column**

Replace the `<td className="p-3">{row.start_date} – {row.end_date}</td>` and `<td className="p-3">{row.required_count}</td>` cells, and add start_time/end_time/notes columns. New `<thead>`:

```tsx
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">סוג תורנות</th>
                  <th className="text-right p-3">מיקום</th>
                  <th className="text-right p-3">תאריך התחלה</th>
                  <th className="text-right p-3">תאריך סיום</th>
                  <th className="text-right p-3">שעת התחלה</th>
                  <th className="text-right p-3">שעת סיום</th>
                  <th className="text-right p-3">נדרש</th>
                  <th className="text-right p-3">הערות</th>
                  <th className="text-right p-3">מכסות יחידה</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
```

Row cells (replacing the old combined-dates cell and required_count cell, inserted after the existing duty_type_name cell and before the existing `duty_location_name` cell — note `duty_location_name` stays plain text, unchanged, per the spec's "stays combobox/remap"... actually `duty_location_name` has no combobox today either; leave its existing plain `<td className="p-3">{row.duty_location_name}</td>` untouched):

```tsx
                      <td className="p-3">
                        {readOnly ? row.start_date : (
                          <input
                            type="date"
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.start_date}
                            onBlur={(e) => setFieldOverride("duty_shifts", row.row, "start_date", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.end_date : (
                          <input
                            type="date"
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.end_date}
                            onBlur={(e) => setFieldOverride("duty_shifts", row.row, "end_date", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.start_time ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.start_time ?? ""}
                            onBlur={(e) => setFieldOverride("duty_shifts", row.row, "start_time", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.end_time ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.end_time ?? ""}
                            onBlur={(e) => setFieldOverride("duty_shifts", row.row, "end_time", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.required_count : (
                          <input
                            type="number"
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.required_count}
                            onBlur={(e) => setFieldOverride("duty_shifts", row.row, "required_count", Number(e.target.value))}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.notes ?? "—" : (
                          <textarea
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.notes ?? ""}
                            onBlur={(e) => setFieldOverride("duty_shifts", row.row, "notes", e.target.value || null)}
                          />
                        )}
                      </td>
```

(The `node_quotas` cell and `StatusChip`/action cells that follow are unchanged.)

- [ ] **Step 2: Type-check**

Run: `npm run typecheck`
Expected: no new errors.

- [ ] **Step 3: Manual verification**

Upload a duty_shifts sheet, edit start_date/end_date/required_count/notes inline, confirm the quota-total-vs-required_count validation (from Task 4's resolver) reacts correctly when `required_count` is edited below the sum of quotas.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ImportSessionReviewPage.tsx
git commit -m "feat: add inline edit to duty_shifts import tab"
```

---

## Task 12: Frontend — assignments tab inline edit + duty_type combobox remap

**Files:**
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`

**Interfaces:**
- Consumes: `AssignmentRow` (already has all needed fields typed); `handlePick`, `applyMapping`, `PendingPickBanner`, `Combobox`, `buildPickerItems` (all already defined in this file, generic over `"duty_type"` kind)
- Produces: nothing new consumed by later tasks

- [ ] **Step 1: Replace the assignments tab body**

Replace the whole `{tab === "assignments" && (...)}` block:

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
                  <th className="text-right p-3">תאריך התחלה</th>
                  <th className="text-right p-3">תאריך סיום</th>
                  <th className="text-right p-3">שעת התחלה</th>
                  <th className="text-right p-3">שעת סיום</th>
                  <th className="text-right p-3">רזרבה</th>
                  <th className="text-right p-3">הערות</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {assignments.map((row: AssignmentRow) => {
                  const canToggle =
                    row.action !== "error" && row.action !== "out_of_scope";
                  const unresolvedType = row.action === "error" && !!row.duty_type_name;
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">{row.full_name}</td>
                      <td className="p-3">{row.personal_number}</td>
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
                                    handlePick("duty_type", row.duty_type_name, `assignments:${row.row}`, pickedId);
                                }}
                              />
                            )}
                            {pendingPick?.rowKey === `assignments:${row.row}` && pendingPick.kind === "duty_type" && (
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
                        {readOnly ? row.start_date : (
                          <input
                            type="date"
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.start_date}
                            onBlur={(e) => setFieldOverride("assignments", row.row, "start_date", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.end_date : (
                          <input
                            type="date"
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.end_date}
                            onBlur={(e) => setFieldOverride("assignments", row.row, "end_date", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.start_time ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.start_time ?? ""}
                            onBlur={(e) => setFieldOverride("assignments", row.row, "start_time", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.end_time ?? "—" : (
                          <input
                            className="border rounded p-1 text-sm w-16 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.end_time ?? ""}
                            onBlur={(e) => setFieldOverride("assignments", row.row, "end_time", e.target.value || null)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? (row.is_reserve ? "כן" : "לא") : (
                          <input
                            type="checkbox"
                            checked={row.is_reserve}
                            onChange={(e) => setFieldOverride("assignments", row.row, "is_reserve", e.target.checked)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.notes ?? "—" : (
                          <textarea
                            className="border rounded p-1 text-sm w-32 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.notes ?? ""}
                            onBlur={(e) => setFieldOverride("assignments", row.row, "notes", e.target.value || null)}
                          />
                        )}
                      </td>
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

Note: `unresolvedType` here is heuristic (`action === "error" && duty_type_name truthy`) since, unlike soldiers/duty_shifts, `AssignmentRow` has no `resolved_duty_type_id` field to check directly — this is acceptable because an assignment row only reaches `"error"` for a handful of reasons (unresolved soldier, unresolved duty type, unresolved location, no matching shift), and showing the combobox whenever there's a `duty_type_name` on an errored row is harmless (picking a valid id and reparsing will simply re-validate and clear the error if that was in fact the problem, or leave a different error visible if it wasn't).

- [ ] **Step 2: Type-check**

Run: `npm run typecheck`
Expected: no new errors.

- [ ] **Step 3: Manual verification**

Upload an assignments sheet with an unresolvable `duty_type_name`, confirm the combobox + "apply to all rows with same name" banner appears and remapping clears the error (mirroring the existing soldiers/duty_shifts UX exactly).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ImportSessionReviewPage.tsx
git commit -m "feat: add inline edit and duty_type remap to assignments import tab"
```

---

## Task 13: Generic `ImportRowDetailModal` component

**Files:**
- Create: `frontend/src/components/ImportRowDetailModal.tsx`

**Interfaces:**
- Consumes: nothing project-specific (pure presentational component)
- Produces: `ImportRowDetailModal` component with props `{ title: string; fields: DetailField[]; onClose: () => void }` where `DetailField = { key: string; label: string; value: unknown; editable?: { type: "text" | "number" | "date" | "checkbox" | "textarea"; onChange: (v: unknown) => void } }` — consumed by Task 14

- [ ] **Step 1: Write the component**

```tsx
export interface DetailField {
  key: string;
  label: string;
  value: unknown;
  editable?: {
    type: "text" | "number" | "date" | "checkbox" | "textarea";
    onChange: (value: unknown) => void;
  };
}

interface Props {
  title: string;
  fields: DetailField[];
  onClose: () => void;
}

function formatReadOnly(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "כן" : "לא";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function ImportRowDetailModal({ title, fields, onClose }: Props) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-lg max-h-[90dvh] overflow-y-auto space-y-3"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center">
          <h3 className="font-semibold text-base">{title}</h3>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>

        <div className="grid grid-cols-1 gap-2">
          {fields.map((f) => (
            <div key={f.key} className="flex flex-col gap-1">
              <span className="text-xs font-medium text-gray-500">{f.label}</span>
              {!f.editable ? (
                <span className="text-sm">{formatReadOnly(f.value)}</span>
              ) : f.editable.type === "checkbox" ? (
                <input
                  type="checkbox"
                  checked={Boolean(f.value)}
                  onChange={(e) => f.editable!.onChange(e.target.checked)}
                />
              ) : f.editable.type === "textarea" ? (
                <textarea
                  className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                  defaultValue={typeof f.value === "string" ? f.value : ""}
                  onBlur={(e) => f.editable!.onChange(e.target.value || null)}
                />
              ) : (
                <input
                  type={f.editable.type}
                  className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                  defaultValue={
                    f.value === null || f.value === undefined
                      ? ""
                      : (f.value as string | number)
                  }
                  onBlur={(e) =>
                    f.editable!.onChange(
                      f.editable!.type === "number"
                        ? (e.target.value === "" ? null : Number(e.target.value))
                        : (e.target.value || null),
                    )
                  }
                />
              )}
            </div>
          ))}
        </div>

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

- [ ] **Step 2: Type-check**

Run: `npm run typecheck`
Expected: no errors (component isn't wired in yet, but must compile standalone).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ImportRowDetailModal.tsx
git commit -m "feat: add generic ImportRowDetailModal component"
```

---

## Task 14: Wire the detail modal into all 8 import tabs

**Files:**
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`

**Interfaces:**
- Consumes: `ImportRowDetailModal`, `DetailField` from Task 13
- Produces: nothing new consumed by later tasks

- [ ] **Step 1: Add state and import**

```ts
import ImportRowDetailModal, { type DetailField } from "../components/ImportRowDetailModal";
```

Add state alongside the existing `dutyTypeFieldsRow`/etc. state:

```ts
  const [detailModal, setDetailModal] = useState<{ title: string; fields: DetailField[] } | null>(null);
```

- [ ] **Step 2: Add a "פרטים" button + click handler per tab**

For each of the 8 tabs, add one more `<td>` (before the `StatusChip` cell, in every tab) with a details button. Example for the `soldiers` tab row (same pattern repeats verbatim for the other 7 tabs, substituting the field list):

```tsx
                      <td className="p-3">
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline text-xs"
                          onClick={() =>
                            setDetailModal({
                              title: `פרטי שורה ${row.row}`,
                              fields: [
                                { key: "personal_number", label: "מספר אישי", value: row.personal_number },
                                { key: "full_name", label: "שם מלא", value: row.full_name, editable: { type: "text", onChange: (v) => setFieldOverride("soldiers", row.row, "full_name", v) } },
                                { key: "rank", label: "דרגה", value: row.rank, editable: { type: "text", onChange: (v) => setFieldOverride("soldiers", row.row, "rank", v) } },
                                { key: "gender", label: "מגדר", value: row.gender, editable: { type: "text", onChange: (v) => setFieldOverride("soldiers", row.row, "gender", v) } },
                                { key: "is_officer", label: "קצין", value: row.is_officer, editable: { type: "checkbox", onChange: (v) => setFieldOverride("soldiers", row.row, "is_officer", v) } },
                                { key: "phone", label: "טלפון", value: row.phone, editable: { type: "text", onChange: (v) => setFieldOverride("soldiers", row.row, "phone", v) } },
                                { key: "email", label: "אימייל", value: row.email, editable: { type: "text", onChange: (v) => setFieldOverride("soldiers", row.row, "email", v) } },
                                { key: "hierarchy_node_name", label: "יחידה", value: row.hierarchy_node_name },
                                { key: "enrolled_at", label: "תאריך שיבוץ", value: row.enrolled_at, editable: { type: "date", onChange: (v) => setFieldOverride("soldiers", row.row, "enrolled_at", v) } },
                                { key: "enlistment_date", label: "תאריך גיוס", value: row.enlistment_date, editable: { type: "date", onChange: (v) => setFieldOverride("soldiers", row.row, "enlistment_date", v) } },
                                { key: "existing_id", label: "מזהה קיים", value: row.existing_id },
                                { key: "errors", label: "שגיאות", value: row.errors },
                                { key: "warnings", label: "אזהרות", value: row.warnings },
                              ],
                            })
                          }
                        >
                          פרטים
                        </button>
                      </td>
```

Apply the exact same structural pattern (a details `<td>` + button + `setDetailModal({ title: ..., fields: [...] })`, placed before the `StatusChip` cell) to the other 7 tabs, using this field table — each row becomes one `{ key, label, value: row.<key>, editable: {...} }` entry (or, for the "no" rows, an entry with no `editable` key at all):

| Tab | Field (`key`) | Label | Editable? | Input type |
|---|---|---|---|---|
| duty_shifts | duty_type_name | סוג תורנות | no | — |
| duty_shifts | resolved_duty_type_id | מזהה סוג תורנות | no | — |
| duty_shifts | duty_location_name | מיקום | no | — |
| duty_shifts | resolved_duty_location_id | מזהה מיקום | no | — |
| duty_shifts | start_date | תאריך התחלה | yes | date |
| duty_shifts | end_date | תאריך סיום | yes | date |
| duty_shifts | start_time | שעת התחלה | yes | text |
| duty_shifts | end_time | שעת סיום | yes | text |
| duty_shifts | required_count | נדרש | yes | number |
| duty_shifts | notes | הערות | yes | textarea |
| duty_shifts | node_quotas | מכסות יחידה | no | — |
| duty_shifts | errors / warnings | שגיאות / אזהרות | no | — |
| shift_templates | name | שם | yes (already wired) | text |
| shift_templates | duty_type_name / resolved_duty_type_id | סוג תורנות | no | — |
| shift_templates | duty_location_name / resolved_duty_location_id | מיקום | no | — |
| shift_templates | recurrence_type | חזרתיות | yes (already wired) | text |
| shift_templates | weekdays | ימים | no (edited via existing weekday buttons, not the modal) | — |
| shift_templates | start_time / end_time | שעות | yes (already wired) | text |
| shift_templates | required_count | נדרש | yes (already wired) | number |
| shift_templates | auto_roll | גלגול אוטומטי | yes (already wired) | checkbox |
| shift_templates | auto_roll_until | עד תאריך | yes (already wired) | date |
| shift_templates | duration_days | משך (ימים) | yes (already wired) | number |
| shift_templates | notes | הערות | yes (already wired) | textarea |
| shift_templates | resolved_eligible_node_ids | יחידות זכאיות | no (edited via existing "ערוך יחידות" button, not the modal) | — |
| shift_templates | existing_id / errors / warnings | — | no | — |
| assignments | personal_number / full_name | מ״א / שם | no | — |
| assignments | duty_type_name | סוג תורנות | no (edited via combobox from Task 12, not the modal) | — |
| assignments | duty_location_name | מיקום | no | — |
| assignments | start_date / end_date | תאריכים | yes | date |
| assignments | start_time / end_time | שעות | yes | text |
| assignments | is_reserve | רזרבה | yes | checkbox |
| assignments | notes | הערות | yes | textarea |
| assignments | resolved_soldier_id / resolved_duty_shift_id / matched_session_row / errors / warnings | — | no | — |
| duty_locations | name | שם | yes (already wired) | text |
| duty_locations | base | בסיס | yes (already wired) | text |
| duty_locations | active | פעיל | yes (already wired) | checkbox |
| duty_locations | existing_id / errors | — | no | — |
| hierarchy | name | שם | yes (already wired) | text |
| hierarchy | level | סוג | yes (already wired) | text |
| hierarchy | parent_name / resolved_parent_id | יחידת אב | no | — |
| hierarchy | commander_personal_number / commander_name / resolved_commander_id | מפקד | no | — |
| hierarchy | duty_manager_refs | אחראי תורנות | no | — |
| hierarchy | existing_id / errors | — | no | — |
| duty_types | every existing field already listed in the tab's own columns (name, score_per_day, description, active, reserve_ratio, reserve_minimum, is_external, contact_name, contact_phone, start_time, end_time, instructions) | (same Hebrew labels as the existing `<thead>`) | yes (already wired) | matches existing cell's input type |
| duty_types | resolved_eligible_node_ids / requirements | יחידות/דרישות | no (edited via existing "ערוך יחידות/דרישות" button, not the modal) | — |
| duty_types | existing_id / errors | — | no | — |
| exemption_types | name / description / is_global / is_medical / is_commander_exemption | (same Hebrew labels as the existing `<thead>`) | yes (already wired) | matches existing cell's input type |
| exemption_types | resolved_duty_type_ids | חל על | no (edited via existing "ערוך חל-על" button, not the modal) | — |
| exemption_types | existing_id / errors | — | no | — |

For every "yes" row, the `onChange` handler is `(v) => setFieldOverride("<tab_group>", row.row, "<key>", v)`, exactly as shown in the soldiers example above.

- [ ] **Step 3: Render the modal once, at the bottom of the component**

Add alongside the other conditionally-rendered modals near the end of the JSX (after the existing `shiftTemplateFieldsRow && (...)` block):

```tsx
      {detailModal && (
        <ImportRowDetailModal
          title={detailModal.title}
          fields={detailModal.fields}
          onClose={() => setDetailModal(null)}
        />
      )}
```

- [ ] **Step 4: Type-check**

Run: `npm run typecheck`
Expected: no new errors.

- [ ] **Step 5: Manual verification**

For each of the 8 tabs, click "פרטים" on a row, confirm every field is visible, confirm editing a scalar field in the modal updates the corresponding inline table cell after the reparse round-trip (and vice versa — editing the inline cell then reopening the modal shows the new value).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ImportSessionReviewPage.tsx
git commit -m "feat: wire row-detail inspect modal into all import review tabs"
```

---

## Task 15: Frontend — soldier profile field parity (new fields in detail modal)

**Files:**
- Modify: `frontend/src/api/importSessions.ts` (`SoldierRow` interface)
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx` (soldiers detail-modal field list from Task 14)

**Interfaces:**
- Consumes: the 10 new fields now emitted by `_resolve_soldiers` (Task 7)
- Produces: nothing new consumed by later tasks (final task in this plan)

- [ ] **Step 1: Extend `SoldierRow` in `frontend/src/api/importSessions.ts`**

```ts
export interface SoldierRow extends RowBase {
  personal_number: string;
  full_name: string;
  rank: string | null;
  gender: string | null;
  is_officer: boolean | null;
  hierarchy_node_id: string | null;
  hierarchy_node_name: string | null;
  enrolled_at: string | null;
  enlistment_date: string | null;
  phone: string | null;
  email: string | null;
  is_career: boolean | null;
  next_rank_date: string | null;
  bahad1_graduate: boolean | null;
  has_military_driving_license: boolean | null;
  military_driving_license_expiry: string | null;
  mandatory_end_date: string | null;
  discharge_date: string | null;
  last_mitvahim_date: string | null;
  last_alal_date: string | null;
  left_at: string | null;
  existing_id: string | null;
}
```

- [ ] **Step 2: Add the 10 new fields to the soldiers detail-modal field list (Task 14's field array)**

Extend the `fields` array in the soldiers tab's "פרטים" button (added in Task 14) with:

```tsx
                                { key: "is_career", label: "קבע", value: row.is_career, editable: { type: "checkbox", onChange: (v) => setFieldOverride("soldiers", row.row, "is_career", v) } },
                                { key: "next_rank_date", label: "תאריך דרגה הבאה", value: row.next_rank_date, editable: { type: "date", onChange: (v) => setFieldOverride("soldiers", row.row, "next_rank_date", v) } },
                                { key: "bahad1_graduate", label: "בוגר בה\"ד 1", value: row.bahad1_graduate, editable: { type: "checkbox", onChange: (v) => setFieldOverride("soldiers", row.row, "bahad1_graduate", v) } },
                                { key: "has_military_driving_license", label: "רישיון נהיגה צבאי", value: row.has_military_driving_license, editable: { type: "checkbox", onChange: (v) => setFieldOverride("soldiers", row.row, "has_military_driving_license", v) } },
                                { key: "military_driving_license_expiry", label: "תוקף רישיון נהיגה", value: row.military_driving_license_expiry, editable: { type: "date", onChange: (v) => setFieldOverride("soldiers", row.row, "military_driving_license_expiry", v) } },
                                { key: "mandatory_end_date", label: "תאריך סיום חובה", value: row.mandatory_end_date, editable: { type: "date", onChange: (v) => setFieldOverride("soldiers", row.row, "mandatory_end_date", v) } },
                                { key: "discharge_date", label: "תאריך שחרור", value: row.discharge_date, editable: { type: "date", onChange: (v) => setFieldOverride("soldiers", row.row, "discharge_date", v) } },
                                { key: "last_mitvahim_date", label: "תאריך מתו\"ם אחרון", value: row.last_mitvahim_date, editable: { type: "date", onChange: (v) => setFieldOverride("soldiers", row.row, "last_mitvahim_date", v) } },
                                { key: "last_alal_date", label: "תאריך אל\"ל אחרון", value: row.last_alal_date, editable: { type: "date", onChange: (v) => setFieldOverride("soldiers", row.row, "last_alal_date", v) } },
                                { key: "left_at", label: "תאריך עזיבה", value: row.left_at, editable: { type: "date", onChange: (v) => setFieldOverride("soldiers", row.row, "left_at", v) } },
```

- [ ] **Step 3: Type-check**

Run: `npm run typecheck`
Expected: no new errors.

- [ ] **Step 4: Manual verification**

Upload a soldiers sheet with values in the new columns, confirm the "פרטים" modal shows and allows editing all 10 new fields, confirm edits round-trip through reparse, and confirm confirming the session creates a `Soldier` with those fields set (cross-check against a running backend, or trust Task 7's backend test coverage if the dev stack isn't up).

- [ ] **Step 5: Run the full frontend test suite for regressions**

Run (from `frontend/`): `npm test`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/importSessions.ts frontend/src/pages/ImportSessionReviewPage.tsx
git commit -m "feat: expose full soldier profile fields in import row detail modal"
```

---

## Final Check

- [ ] Run the full backend suite: `pytest -q` (from `backend/`, venv active)
- [ ] Run `npm run lint` and `npm run typecheck` (from `frontend/`)
- [ ] Manually walk through all 8 tabs in the review UI with a sample multi-sheet Excel file, confirming inline edit + detail modal + (for assignments) combobox remap all work end-to-end, then confirm the session and verify the created/updated records in the database match what was edited.
