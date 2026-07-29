# Excel settings/bug-report sheets + ניקוד help tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `system_settings` and `bug_reports` as sheets in the app's existing unified Excel export/import pipeline, and add a `ניקוד` (scoring) tab to the existing help modal.

**Architecture:** The app already has one active import pipeline: upload → `v1_standard.py` parser → `ParsedImportData` → per-sheet "resolve" function (builds preview rows with resolved foreign keys and validation errors) → `confirm_session()` applies each resolved row to the DB. Export is a separate, simpler set of per-sheet writer functions in `config_export.py` that read the DB straight into an `openpyxl` worksheet. This plan adds two sheets end-to-end through both pipelines, plus one new frontend-only help tab that needs no backend changes.

**Tech Stack:** FastAPI + SQLAlchemy (backend), React + TypeScript + Vitest (frontend), openpyxl for `.xlsx` I/O, pytest for backend tests.

## Global Constraints

- Hebrew UI strings throughout (error messages, labels, column headers) — English code/identifiers, matching every existing file touched in this plan.
- No changes to the JSON export/import paths for settings (`/admin/system-settings/export`/`import`) or bug reports (`/admin/bug-reports/import`) — Excel is additive.
- No changes to `duty_types`/`hierarchy`/`exemption_types`/`duty_locations` import logic — already works.
- Screenshots and `json_file_path` are never included in the Excel sheet for bug reports.
- `reporter_id` on an existing `BugReport` is never changed by an import row, even if the row's `reporter_personal_number` differs from the record's current reporter.

---

### Task 1: Schema + parser support for `system_settings` and `bug_reports` sheets

**Files:**
- Modify: `backend/app/services/import_parsers/schema.py`
- Modify: `backend/app/services/import_parsers/v1_standard.py`
- Test: `backend/app/services/tests/test_import_parser_v1.py`

**Interfaces:**
- Produces: `ImportSystemSettingRow(source_row: int, key: str, value_json: str)`,
  `ImportBugReportRow(source_row: int, id: str | None, reporter_personal_number: str,
  description: str, severity: str, route: str, status: str, created_at: str | None,
  nav_history_json: str | None, audit_snapshot_json: str | None, user_snapshot_json: str | None)`,
  both added to `ParsedImportData` as `system_settings: list[ImportSystemSettingRow] = []`
  and `bug_reports: list[ImportBugReportRow] = []`. Task 2/3 resolvers consume
  `data.system_settings` / `data.bug_reports`.

- [ ] **Step 1: Write the failing parser tests**

Add to `backend/app/services/tests/test_import_parser_v1.py` (append at end of file):

```python
def _wb_with_system_settings_sheet(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("system_settings")
    ws.append(["key", "value_json"])
    for r in rows:
        ws.append(r)
    return wb


def test_parses_system_settings_sheet():
    wb = _wb_with_system_settings_sheet([
        ["algorithm.max_duties_per_window", "8"],
        ["telegram.enabled", "true"],
        ["registration.default_role", '"soldier"'],
    ])
    data = V1StandardParser().parse(wb)
    assert len(data.system_settings) == 3
    assert data.system_settings[0].key == "algorithm.max_duties_per_window"
    assert data.system_settings[0].value_json == "8"
    assert data.system_settings[1].value_json == "true"
    assert data.system_settings[2].value_json == '"soldier"'


def test_system_settings_sheet_absent_gives_empty_list():
    wb = _wb_with_duty_shifts_sheet([
        ["שמירה", "בסיס א", "15.06.2024", "16.06.2024", "", "", 5, "", ""],
    ])
    data = V1StandardParser().parse(wb)
    assert data.system_settings == []


def _wb_with_bug_reports_sheet(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("bug_reports")
    ws.append([
        "id", "reporter_personal_number", "description", "severity", "route", "status",
        "created_at", "nav_history_json", "audit_snapshot_json", "user_snapshot_json",
    ])
    for r in rows:
        ws.append(r)
    return wb


def test_parses_bug_reports_sheet():
    wb = _wb_with_bug_reports_sheet([
        ["", "1234567", "הכפתור לא עובד", "medium", "/planning/export", "open",
         "", "", "", ""],
    ])
    data = V1StandardParser().parse(wb)
    assert len(data.bug_reports) == 1
    row = data.bug_reports[0]
    assert row.id is None
    assert row.reporter_personal_number == "1234567"
    assert row.description == "הכפתור לא עובד"
    assert row.severity == "medium"
    assert row.route == "/planning/export"
    assert row.status == "open"
    assert row.nav_history_json is None


def test_parses_bug_reports_sheet_with_id_and_json_columns():
    wb = _wb_with_bug_reports_sheet([
        ["11111111-1111-1111-1111-111111111111", "1234567", "תקלה", "high",
         "/x", "resolved", "2026-01-01T00:00:00+00:00",
         '[{"path": "/a"}]', '[{"action": "x"}]', '{"role": "soldier"}'],
    ])
    data = V1StandardParser().parse(wb)
    row = data.bug_reports[0]
    assert row.id == "11111111-1111-1111-1111-111111111111"
    assert row.nav_history_json == '[{"path": "/a"}]'
    assert row.audit_snapshot_json == '[{"action": "x"}]'
    assert row.user_snapshot_json == '{"role": "soldier"}'


def test_bug_reports_sheet_absent_gives_empty_list():
    wb = _wb_with_duty_shifts_sheet([
        ["שמירה", "בסיס א", "15.06.2024", "16.06.2024", "", "", 5, "", ""],
    ])
    data = V1StandardParser().parse(wb)
    assert data.bug_reports == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_import_parser_v1.py -k "system_settings or bug_reports" -v`
Expected: FAIL — `ParsedImportData` has no field `system_settings`/`bug_reports` (Pydantic will
error before the assertions even run, since the parser doesn't produce those attributes).

- [ ] **Step 3: Add the row schemas**

In `backend/app/services/import_parsers/schema.py`, add after `ImportSoldierExemptionRow`
(before `class ParsedImportData`):

```python
class ImportSystemSettingRow(BaseModel):
    source_row: int
    key: str
    value_json: str


class ImportBugReportRow(BaseModel):
    source_row: int
    id: str | None = None
    reporter_personal_number: str
    description: str
    severity: str
    route: str
    status: str
    created_at: str | None = None
    nav_history_json: str | None = None
    audit_snapshot_json: str | None = None
    user_snapshot_json: str | None = None
```

Then add two fields to `ParsedImportData`, right after `soldier_exemptions`:

```python
    soldier_exemptions: list[ImportSoldierExemptionRow] = []
    system_settings: list[ImportSystemSettingRow] = []
    bug_reports: list[ImportBugReportRow] = []
```

- [ ] **Step 4: Parse the two sheets in `v1_standard.py`**

In `backend/app/services/import_parsers/v1_standard.py`, add both names to `KNOWN_SHEETS`:

```python
KNOWN_SHEETS = {
    "soldiers", "duty_shifts", "assignments", "duty_locations", "hierarchy",
    "duty_types", "exemption_types", "shift_templates",
    "swap_requests", "exemption_requests", "soldier_field_updates",
    "soldier_enrollment_requests", "personal_constraints", "soldier_exemptions",
    "system_settings", "bug_reports",
}
```

Add the two imports to the `from app.services.import_parsers.schema import (...)` block
(alphabetically, matching the existing ordering style):

```python
    ImportBugReportRow,
    ...
    ImportSystemSettingRow,
```

In `V1StandardParser.parse()`, add after the `soldier_exemptions` list comprehension
(right before the `return ParsedImportData(...)` call):

```python
        system_settings = [
            ImportSystemSettingRow(
                source_row=r["_row"],
                key=str(r.get("key") or "").strip(),
                value_json=str(r["value_json"]).strip() if r.get("value_json") is not None else "",
            )
            for r in _sheet_rows(wb, "system_settings")
        ]

        bug_reports = [
            ImportBugReportRow(
                source_row=r["_row"],
                id=str(r.get("id") or "").strip() or None,
                reporter_personal_number=str(r.get("reporter_personal_number") or "").strip(),
                description=str(r.get("description") or "").strip(),
                severity=str(r.get("severity") or "").strip(),
                route=str(r.get("route") or "").strip(),
                status=str(r.get("status") or "").strip(),
                created_at=str(r.get("created_at") or "").strip() or None,
                nav_history_json=str(r.get("nav_history_json") or "").strip() or None,
                audit_snapshot_json=str(r.get("audit_snapshot_json") or "").strip() or None,
                user_snapshot_json=str(r.get("user_snapshot_json") or "").strip() or None,
            )
            for r in _sheet_rows(wb, "bug_reports")
        ]
```

And add both to the `return ParsedImportData(...)` call, right after `soldier_exemptions=soldier_exemptions,`:

```python
            soldier_exemptions=soldier_exemptions,
            system_settings=system_settings,
            bug_reports=bug_reports,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_import_parser_v1.py -v`
Expected: PASS (all tests in the file, not just the new ones — confirms no regression).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/import_parsers/schema.py backend/app/services/import_parsers/v1_standard.py backend/app/services/tests/test_import_parser_v1.py
git commit -m "feat: parse system_settings and bug_reports Excel sheets"
```

---

### Task 2: Resolve + apply `system_settings` rows on import

**Files:**
- Modify: `backend/app/services/import_approvals.py`
- Modify: `backend/app/services/import_sessions.py`
- Modify: `backend/app/routes/import_sessions.py`
- Test: `backend/app/services/tests/test_import_sessions_service.py`

**Interfaces:**
- Consumes: `ImportSystemSettingRow` from Task 1 (`data.system_settings`); `set_setting(session, key, value, *, actor_id)` from `app.services.settings_loader` (existing).
- Produces: `resolve_system_settings(session, data, overrides=None) -> list[dict]` — each dict has
  `row, action ("new"|"update"|"error"), errors, key, value_json, parsed_value`. Consumed by
  `confirm_session()`'s new `system_settings` block in this same task.

- [ ] **Step 1: Write the failing service test**

Add to `backend/app/services/tests/test_import_sessions_service.py` (append at end of file):

```python
def _wb_with_system_settings(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("system_settings")
    ws.append(["key", "value_json"])
    for r in rows:
        ws.append(r)
    return wb


def test_system_settings_import_creates_and_updates(admin_session):
    from app.db.models import SystemSetting

    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    admin_session.add(SystemSetting(key="algorithm.max_duties_per_window", value=5, updated_by=admin.id))
    admin_session.commit()

    wb = _wb_with_system_settings([
        ["algorithm.max_duties_per_window", "8"],
        ["telegram.enabled", "true"],
    ])
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    rows = sess.parsed_state["system_settings"]
    assert {r["key"]: r["action"] for r in rows} == {
        "algorithm.max_duties_per_window": "update",
        "telegram.enabled": "new",
    }

    confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    updated = admin_session.get(SystemSetting, "algorithm.max_duties_per_window")
    assert updated.value == 8
    created = admin_session.get(SystemSetting, "telegram.enabled")
    assert created.value is True


def test_system_settings_import_invalid_json_is_row_error(admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    wb = _wb_with_system_settings([["some.key", "{not valid json"]])
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row = sess.parsed_state["system_settings"][0]
    assert row["action"] == "error"
    assert row["errors"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_import_sessions_service.py -k system_settings_import -v`
Expected: FAIL — `sess.parsed_state["system_settings"]` is `[]` (not resolved yet), or `KeyError`.

- [ ] **Step 3: Add `resolve_system_settings` to `import_approvals.py`**

In `backend/app/services/import_approvals.py`, add `import json` to the top imports and append
this function at the end of the file:

```python
def resolve_system_settings(
    session: Session, data: ParsedImportData, overrides: dict[str, dict] | None = None
) -> list[dict]:
    overrides = overrides or {}
    existing_keys = {
        row[0] for row in session.execute(select(SystemSetting.key)).all()
    }
    out = []
    for row in data.system_settings:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        key = field("key", row.key)
        value_json = field("value_json", row.value_json)

        if not key:
            errors.append("חסר מפתח")

        parsed_value = None
        if not errors:
            try:
                parsed_value = json.loads(value_json) if value_json != "" else None
            except Exception as exc:
                errors.append(f"JSON לא תקין בעמודת value_json: {exc}")

        action = "error" if errors else ("update" if key in existing_keys else "new")
        out.append({
            "row": row.source_row, "action": action, "errors": errors,
            "key": key, "value_json": value_json, "parsed_value": parsed_value,
        })
    return out
```

Add `SystemSetting` to the `from app.db.models import (...)` block in that file (keep
alphabetical: `SoldierFieldUpdate, SwapCandidate, SwapRequest, SystemSetting,`).

- [ ] **Step 4: Wire it into `_resolve_and_score` and `confirm_session`**

In `backend/app/services/import_sessions.py`:

Add `resolve_system_settings` to the `from app.services.import_approvals import (...)` block
(alphabetical): `resolve_soldier_field_updates, resolve_swap_requests, resolve_system_settings,`.

Add `SystemSetting` to the `from app.db.models import (...)` block (alphabetical, near
`SoldierFieldUpdate`).

Add `from app.services.settings_loader import set_setting` as a new import line.

In `_resolve_and_score()`, add one line to the returned dict, right after `"exemption_types": ...,`:

```python
        "system_settings": resolve_system_settings(session, data, fo.get("system_settings", {})),
```

In `confirm_session()`, add a new block right after the `# ── Exemption types` block ends
(after its `except Exception as exc: errors.append(...)` line, before `# ── Personal constraints`):

```python
    # ── System settings ────────────────────────────────────────────────
    for row in state.get("system_settings", []):
        effective = _effective_action(selections, "system_settings", row)
        if row["action"] == "error" or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                set_setting(session, key=row["key"], value=row["parsed_value"], actor_id=actor.id)
                if effective == "new":
                    created += 1
                else:
                    updated += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "system_settings", "error": str(exc)})
```

- [ ] **Step 5: Add the row-count summary in the route file**

In `backend/app/routes/import_sessions.py`, in `_session_summary()`, add a line to the
`row_summary` dict right after `"exemption_types": len(state.get("exemption_types", [])),`:

```python
            "system_settings": len(state.get("system_settings", [])),
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_import_sessions_service.py -v`
Expected: PASS (full file, confirms no regression to existing resolve/confirm tests).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/import_approvals.py backend/app/services/import_sessions.py backend/app/routes/import_sessions.py backend/app/services/tests/test_import_sessions_service.py
git commit -m "feat: resolve and apply system_settings rows on Excel import"
```

---

### Task 3: Resolve + apply `bug_reports` rows on import

**Files:**
- Modify: `backend/app/services/import_approvals.py`
- Modify: `backend/app/services/import_sessions.py`
- Modify: `backend/app/routes/import_sessions.py`
- Test: `backend/app/services/tests/test_import_sessions_service.py`

**Interfaces:**
- Consumes: `ImportBugReportRow` from Task 1 (`data.bug_reports`); `_soldiers_by_pn(session)`
  (existing, in `import_approvals.py`).
- Produces: `resolve_bug_reports(session, data, overrides=None) -> list[dict]` — each dict has
  `row, action, errors, id, reporter_personal_number, resolved_reporter_id, description,
  severity, route, status, created_at, nav_history, audit_snapshot, user_snapshot, existing_id`.
  Consumed by `confirm_session()`'s new `bug_reports` block in this same task.

- [ ] **Step 1: Write the failing service test**

Add to `backend/app/services/tests/test_import_sessions_service.py` (append at end of file):

```python
def _wb_with_bug_reports(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("bug_reports")
    ws.append([
        "id", "reporter_personal_number", "description", "severity", "route", "status",
        "created_at", "nav_history_json", "audit_snapshot_json", "user_snapshot_json",
    ])
    for r in rows:
        ws.append(r)
    return wb


def test_bug_report_import_creates_new_report(admin_session):
    from app.db.models import BugReport

    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    reporter = create_soldier(admin_session, personal_number="7778889", role="soldier")
    admin_session.commit()

    wb = _wb_with_bug_reports([
        ["", "7778889", "הכפתור לא עובד", "medium", "/planning/export", "open",
         "", "", "", ""],
    ])
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row = sess.parsed_state["bug_reports"][0]
    assert row["action"] == "new"
    assert row["resolved_reporter_id"] == str(reporter.id)

    confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    created = admin_session.execute(
        select(BugReport).where(BugReport.description == "הכפתור לא עובד")
    ).scalar_one()
    assert created.reporter_id == reporter.id
    assert created.severity == "medium"
    assert created.status == "open"


def test_bug_report_import_updates_status_by_id_without_changing_reporter(admin_session):
    from app.db.models import BugReport

    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    original_reporter = create_soldier(admin_session, personal_number="1112223", role="soldier")
    other_soldier = create_soldier(admin_session, personal_number="3332221", role="soldier")
    existing = BugReport(
        reporter_id=original_reporter.id, description="ישן", severity="low",
        route="/x", status="open",
    )
    admin_session.add(existing)
    admin_session.commit()
    admin_session.refresh(existing)

    wb = _wb_with_bug_reports([
        [str(existing.id), "3332221", "ישן", "low", "/x", "resolved", "", "", "", ""],
    ])
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row = sess.parsed_state["bug_reports"][0]
    assert row["action"] == "update"

    confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()
    admin_session.refresh(existing)

    assert existing.status == "resolved"
    assert existing.reporter_id == original_reporter.id  # unchanged despite mismatched row


def test_bug_report_import_unresolvable_reporter_is_row_error(admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    wb = _wb_with_bug_reports([
        ["", "0000000", "תקלה", "low", "/x", "open", "", "", "", ""],
    ])
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    row = sess.parsed_state["bug_reports"][0]
    assert row["action"] == "error"
    assert row["errors"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_import_sessions_service.py -k bug_report_import -v`
Expected: FAIL — `sess.parsed_state["bug_reports"]` is `[]`, or `KeyError`.

- [ ] **Step 3: Add `resolve_bug_reports` to `import_approvals.py`**

Append at the end of `backend/app/services/import_approvals.py`:

```python
def resolve_bug_reports(
    session: Session, data: ParsedImportData, overrides: dict[str, dict] | None = None
) -> list[dict]:
    soldiers_by_pn = _soldiers_by_pn(session)
    overrides = overrides or {}
    out = []
    for row in data.bug_reports:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        reporter_pn = field("reporter_personal_number", row.reporter_personal_number)
        description = field("description", row.description)
        severity = field("severity", row.severity)
        route = field("route", row.route)
        status = field("status", row.status)
        created_at = field("created_at", row.created_at)

        reporter = soldiers_by_pn.get(reporter_pn) if reporter_pn else None
        if reporter is None:
            errors.append(f"מדווח לא מזוהה '{reporter_pn}'")
        if severity not in ("low", "medium", "high"):
            errors.append(f"חומרה לא תקינה '{severity}'")
        if status not in ("open", "in_progress", "resolved"):
            errors.append(f"סטטוס לא תקין '{status}'")
        if not description:
            errors.append("חסר תיאור")
        if not route:
            errors.append("חסר route")

        def _decode(raw: str | None, label: str):
            if not raw:
                return None
            try:
                return json.loads(raw)
            except Exception as exc:
                errors.append(f"JSON לא תקין בעמודת {label}: {exc}")
                return None

        nav_history = _decode(field("nav_history_json", row.nav_history_json), "nav_history_json")
        audit_snapshot = _decode(field("audit_snapshot_json", row.audit_snapshot_json), "audit_snapshot_json")
        user_snapshot = _decode(field("user_snapshot_json", row.user_snapshot_json), "user_snapshot_json")

        existing = None
        if row.id:
            try:
                existing = session.get(BugReport, uuid.UUID(row.id))
            except ValueError:
                errors.append(f"מזהה לא תקין '{row.id}'")

        action = "error" if errors else ("update" if existing is not None else "new")
        out.append({
            "row": row.source_row, "action": action, "errors": errors,
            "id": row.id,
            "reporter_personal_number": reporter_pn,
            "resolved_reporter_id": str(reporter.id) if reporter is not None else None,
            "description": description, "severity": severity, "route": route, "status": status,
            "created_at": created_at,
            "nav_history": nav_history, "audit_snapshot": audit_snapshot, "user_snapshot": user_snapshot,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out
```

Add `BugReport` to the `from app.db.models import (...)` block in `import_approvals.py`
(alphabetical, first entry).

- [ ] **Step 4: Wire it into `_resolve_and_score` and `confirm_session`**

In `backend/app/services/import_sessions.py`:

Add `resolve_bug_reports` to the `from app.services.import_approvals import (...)` block
(alphabetical): `resolve_bug_reports, resolve_exemption_requests, ...`.

Add `BugReport` to the `from app.db.models import (...)` block (alphabetical, first entry).

In `_resolve_and_score()`, add right after the `"system_settings": ...,` line added in Task 2:

```python
        "bug_reports": resolve_bug_reports(session, data, fo.get("bug_reports", {})),
```

In `confirm_session()`, add a new block right after the `system_settings` block added in
Task 2 (before `# ── Personal constraints`):

```python
    # ── Bug reports ─────────────────────────────────────────────────────
    for row in state.get("bug_reports", []):
        effective = _effective_action(selections, "bug_reports", row)
        if row["action"] == "error" or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                if effective == "new":
                    br = BugReport(
                        reporter_id=uuid.UUID(row["resolved_reporter_id"]),
                        description=row["description"],
                        severity=row["severity"],
                        route=row["route"],
                        status=row["status"],
                        nav_history=row.get("nav_history"),
                        audit_snapshot=row.get("audit_snapshot"),
                        user_snapshot=row.get("user_snapshot"),
                    )
                    session.add(br)
                    session.flush()
                    if row.get("created_at"):
                        br.created_at = datetime.fromisoformat(row["created_at"])
                    created += 1
                elif effective == "update" and row.get("existing_id"):
                    br = session.get(BugReport, uuid.UUID(row["existing_id"]))
                    if br is not None:
                        br.description = row["description"]
                        br.severity = row["severity"]
                        br.route = row["route"]
                        br.status = row["status"]
                        updated += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "bug_reports", "error": str(exc)})
```

- [ ] **Step 5: Add the row-count summary in the route file**

In `backend/app/routes/import_sessions.py`, in `_session_summary()`, add right after the
`"system_settings": ...,` line added in Task 2:

```python
            "bug_reports": len(state.get("bug_reports", [])),
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_import_sessions_service.py -v`
Expected: PASS (full file).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/import_approvals.py backend/app/services/import_sessions.py backend/app/routes/import_sessions.py backend/app/services/tests/test_import_sessions_service.py
git commit -m "feat: resolve and apply bug_reports rows on Excel import"
```

---

### Task 4: Export writers for `system_settings` and `bug_reports`

**Files:**
- Modify: `backend/app/routes/config_export.py`
- Test: `backend/app/routes/tests/test_config_export.py` (new file)

**Interfaces:**
- Produces: `_write_system_settings(wb, session)` and `_write_bug_reports(wb, session)`,
  registered in `_WRITERS` and `ALL_SHEETS` under keys `"system_settings"` and `"bug_reports"`.
  These are consumed by the existing `GET /config/export?sheets=...` route — no route code
  changes needed beyond the dict/list registration.

- [ ] **Step 1: Write the failing writer tests**

Create `backend/app/routes/tests/test_config_export.py`:

```python
from __future__ import annotations

import json

import openpyxl

from app.db.models import BugReport, SystemSetting
from app.routes.config_export import _write_bug_reports, _write_system_settings
from tests.helpers import create_soldier


def _rows(ws):
    return [
        [c.value for c in row]
        for row in ws.iter_rows(min_row=2)
        if any(c.value is not None for c in row)
    ]


def test_write_system_settings_writes_key_and_json_value(admin_session):
    admin_session.add(SystemSetting(key="algorithm.max_duties_per_window", value=8, updated_by=None))
    admin_session.add(SystemSetting(key="telegram.enabled", value=True, updated_by=None))
    admin_session.commit()

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    _write_system_settings(wb, admin_session)

    rows = {r[0]: r[1] for r in _rows(wb["system_settings"])}
    assert rows["algorithm.max_duties_per_window"] == "8"
    assert rows["telegram.enabled"] == "true"


def test_write_system_settings_excludes_hidden_keys(admin_session):
    admin_session.add(SystemSetting(key="system.holding_node_id", value="abc", updated_by=None))
    admin_session.commit()

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    _write_system_settings(wb, admin_session)

    assert _rows(wb["system_settings"]) == []


def test_write_bug_reports_resolves_reporter_and_serializes_json_columns(admin_session):
    reporter = create_soldier(admin_session, personal_number="5556667", role="soldier")
    admin_session.add(BugReport(
        reporter_id=reporter.id, description="בעיה", severity="high", route="/x", status="open",
        nav_history=[{"path": "/a"}], audit_snapshot=None, user_snapshot={"role": "soldier"},
    ))
    admin_session.commit()

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    _write_bug_reports(wb, admin_session)

    row = _rows(wb["bug_reports"])[0]
    header = [c.value for c in wb["bug_reports"][1]]
    data = dict(zip(header, row))
    assert data["reporter_personal_number"] == "5556667"
    assert data["description"] == "בעיה"
    assert json.loads(data["nav_history_json"]) == [{"path": "/a"}]
    assert data["audit_snapshot_json"] == ""
    assert json.loads(data["user_snapshot_json"]) == {"role": "soldier"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest app/routes/tests/test_config_export.py -v`
Expected: FAIL — `ImportError: cannot import name '_write_system_settings'`.

- [ ] **Step 3: Implement the two writers**

In `backend/app/routes/config_export.py`, add `json` stays imported (already is), add
`BugReport` and `SystemSetting` to the `from app.db.models import (...)` block (alphabetical).

Add both functions right after `_write_exemption_types` (before `_WRITERS = {`):

```python
_HIDDEN_SETTING_KEYS = {"system.holding_node_id"}


def _write_system_settings(wb: openpyxl.Workbook, session: Session) -> None:
    ws = wb.create_sheet("system_settings")
    ws.append(["key", "value_json"])
    for setting in session.execute(select(SystemSetting)).scalars():
        if setting.key in _HIDDEN_SETTING_KEYS:
            continue
        ws.append([setting.key, json.dumps(setting.value, ensure_ascii=False)])


def _write_bug_reports(wb: openpyxl.Workbook, session: Session) -> None:
    ws = wb.create_sheet("bug_reports")
    ws.append([
        "id", "reporter_personal_number", "description", "severity", "route", "status",
        "created_at", "nav_history_json", "audit_snapshot_json", "user_snapshot_json",
    ])
    soldiers_by_id = {s.id: s for s in session.execute(select(Soldier)).scalars()}
    for br in session.execute(select(BugReport)).scalars():
        reporter = soldiers_by_id.get(br.reporter_id)
        ws.append([
            str(br.id),
            reporter.personal_number if reporter else "",
            br.description, br.severity, br.route, br.status,
            br.created_at.isoformat() if br.created_at else "",
            json.dumps(br.nav_history, ensure_ascii=False) if br.nav_history else "",
            json.dumps(br.audit_snapshot, ensure_ascii=False) if br.audit_snapshot else "",
            json.dumps(br.user_snapshot, ensure_ascii=False) if br.user_snapshot else "",
        ])
```

Update `_WRITERS` and `ALL_SHEETS`:

```python
ALL_SHEETS = ["duty_types", "duty_locations", "hierarchy", "exemption_types", "system_settings", "bug_reports"]
```

```python
_WRITERS = {
    "duty_locations": _write_duty_locations,
    "hierarchy": _write_hierarchy,
    "duty_types": _write_duty_types,
    "exemption_types": _write_exemption_types,
    "system_settings": _write_system_settings,
    "bug_reports": _write_bug_reports,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest app/routes/tests/test_config_export.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/config_export.py backend/app/routes/tests/test_config_export.py
git commit -m "feat: export system_settings and bug_reports Excel sheets"
```

---

### Task 5: Frontend types + `ExportPage` checkboxes

**Files:**
- Modify: `frontend/src/api/importSessions.ts`
- Modify: `frontend/src/pages/planning/ExportPage.tsx`
- Modify: `frontend/src/pages/planning/ExportPage.test.tsx`

**Interfaces:**
- Produces: `SystemSettingImportRow`, `BugReportImportRow` (exported from `api/importSessions.ts`),
  both added to `ParsedState`. Consumed by Task 6 (`ImportSessionReviewPage.tsx`).

- [ ] **Step 1: Add the new row types and `ParsedState` fields**

In `frontend/src/api/importSessions.ts`, add after `ExemptionTypeImportRow` (around line 158):

```typescript
export interface SystemSettingImportRow extends RowBase {
  key: string;
  value_json: string;
  parsed_value: unknown;
}

export interface BugReportImportRow extends RowBase {
  id: string | null;
  reporter_personal_number: string;
  resolved_reporter_id: string | null;
  description: string;
  severity: string;
  route: string;
  status: string;
  created_at: string | null;
  nav_history: unknown;
  audit_snapshot: unknown;
  user_snapshot: unknown;
  existing_id: string | null;
}
```

In the `ParsedState` interface, add after `exemption_types: ExemptionTypeImportRow[];`:

```typescript
  system_settings: SystemSettingImportRow[];
  bug_reports: BugReportImportRow[];
```

- [ ] **Step 2: Write the failing `ExportPage` test**

In `frontend/src/pages/planning/ExportPage.test.tsx`, find the existing test that asserts on
`CONFIG_SHEET_OPTIONS` checkbox labels (search for `"פטורים"` or `"היררכיה"` in that file to
locate it) and add two assertions for the new labels next to the existing ones, e.g. if the
existing test does `expect(screen.getByText("היררכיה")).toBeInTheDocument();`, add:

```typescript
    expect(screen.getByText("הגדרות מערכת")).toBeInTheDocument();
    expect(screen.getByText("דוחות תקלות")).toBeInTheDocument();
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/planning/ExportPage.test.tsx`
Expected: FAIL — text "הגדרות מערכת" / "דוחות תקלות" not found.

- [ ] **Step 4: Add the checkboxes**

In `frontend/src/pages/planning/ExportPage.tsx`, update `CONFIG_SHEET_OPTIONS`:

```typescript
const CONFIG_SHEET_OPTIONS = [
  { key: "duty_types", label: "סוגי תורנות" },
  { key: "duty_locations", label: "מיקומי תורנות" },
  { key: "hierarchy", label: "היררכיה" },
  { key: "exemption_types", label: "פטורים" },
  { key: "system_settings", label: "הגדרות מערכת" },
  { key: "bug_reports", label: "דוחות תקלות" },
] as const;
```

No other changes needed in this file — `ALL_KEYS`, `toggleAll`, and `handleExport` already
derive from `CONFIG_SHEET_OPTIONS` generically and fetch from `/config/export`, which Task 4
already wired up.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/planning/ExportPage.test.tsx`
Expected: PASS.

- [ ] **Step 6: Run the frontend typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors (confirms `ParsedState`'s two new required fields don't break any other
file yet — Task 6 fixes the one place that will need updating, `ImportSessionReviewPage.tsx`
and its test, so run this again at the end of Task 6).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/importSessions.ts frontend/src/pages/planning/ExportPage.tsx frontend/src/pages/planning/ExportPage.test.tsx
git commit -m "feat: add system_settings and bug_reports to the export sheet picker"
```

---

### Task 6: `ImportSessionReviewPage` tabs for `system_settings` and `bug_reports`

**Files:**
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`
- Modify: `frontend/src/pages/ImportSessionReviewPage.test.tsx`

**Interfaces:**
- Consumes: `SystemSettingImportRow`, `BugReportImportRow` from Task 5.

- [ ] **Step 1: Update the test's mock parsed-state builder**

In `frontend/src/pages/ImportSessionReviewPage.test.tsx`, in `makeDraftDetail()`'s
`parsed_state` object, add two more empty arrays right after `exemption_types: [],`:

```typescript
      system_settings: [],
      bug_reports: [],
```

- [ ] **Step 2: Write the failing test for the new tabs**

Add a new test inside the `describe("ImportSessionReviewPage", ...)` block, right after the
existing `"renders the duty_locations tab with row action controls"` test, following that
test's exact `makeDraftDetail()` + `vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail)`
+ `renderPage()` + `fireEvent.click(screen.getByText(...))` pattern:

```typescript
  it("renders the system_settings and bug_reports tabs with row counts", async () => {
    const detail = makeDraftDetail();
    detail.parsed_state.system_settings = [
      { row: 2, action: "new", errors: [], key: "telegram.enabled", value_json: "true", parsed_value: true },
    ];
    detail.parsed_state.bug_reports = [
      {
        row: 2, action: "new", errors: [], id: null,
        reporter_personal_number: "1234567", resolved_reporter_id: "s-1",
        description: "בעיה", severity: "low", route: "/x", status: "open",
        created_at: null, nav_history: null, audit_snapshot: null, user_snapshot: null,
        existing_id: null,
      },
    ];
    vi.mocked(importSessionsApi.getSession).mockResolvedValue(detail);

    renderPage();
    await screen.findByDisplayValue("יוסי כהן");

    expect(screen.getByText("הגדרות מערכת (1)")).toBeInTheDocument();
    expect(screen.getByText("דוחות תקלות (1)")).toBeInTheDocument();

    fireEvent.click(screen.getByText("הגדרות מערכת (1)"));
    expect(await screen.findByText("telegram.enabled")).toBeInTheDocument();

    fireEvent.click(screen.getByText("דוחות תקלות (1)"));
    expect(await screen.findByText("בעיה")).toBeInTheDocument();
  });
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/ImportSessionReviewPage.test.tsx -t "system_settings and bug_reports"`
Expected: FAIL — tab labels not found (TypeScript compile may also fail first since `TabKey`/
`GroupKey` don't include the new keys yet — that's expected at this point).

- [ ] **Step 4: Add the type unions, imports, and tab list entries**

In `frontend/src/pages/ImportSessionReviewPage.tsx`:

Add `type SystemSettingImportRow` and `type BugReportImportRow` to the import block from
`../api/importSessions` (alphabetical among the existing `type ...ImportRow` imports).

Add `"system_settings" | "bug_reports"` to both the `TabKey` and `GroupKey` union type
definitions, right after `"exemption_types"` in each.

In the component body, add `system_settings, bug_reports,` to the destructuring of
`detail.parsed_state` (right after `exemption_types,`).

In the tab list array (the `[TabKey, string][]` literal), add two entries right after the
`exemption_types` entry:

```typescript
              ["system_settings", `הגדרות מערכת (${system_settings.length})`],
              ["bug_reports", `דוחות תקלות (${bug_reports.length})`],
```

- [ ] **Step 5: Add the two table sections**

Add right after the closing `)}` of the `exemption_types` tab block (before the
`personal_constraints` tab block begins):

```typescript
        {tab === "system_settings" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">מפתח</th>
                  <th className="text-right p-3">ערך (JSON)</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {system_settings.map((row: SystemSettingImportRow) => {
                  const canToggle = row.action !== "error";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">{row.key}</td>
                      <td className="p-3">
                        {readOnly ? row.value_json : (
                          <input
                            className="border rounded p-1 text-sm w-40 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.value_json}
                            onBlur={(e) => setFieldOverride("system_settings", row.row, "value_json", e.target.value)}
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
                              value={currentSelection("system_settings", row)}
                              onChange={(e) => setRowAction("system_settings", row.row, e.target.value)}
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

        {tab === "bug_reports" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 border-b dark:border-gray-700">
                  <th className="text-right p-3">מדווח</th>
                  <th className="text-right p-3">תיאור</th>
                  <th className="text-right p-3">חומרה</th>
                  <th className="text-right p-3">route</th>
                  <th className="text-right p-3">סטטוס תקלה</th>
                  <th className="text-right p-3">סטטוס</th>
                  {!readOnly && <th className="text-right p-3">פעולה</th>}
                </tr>
              </thead>
              <tbody>
                {bug_reports.map((row: BugReportImportRow) => {
                  const canToggle = row.action !== "error";
                  return (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="p-3">{row.reporter_personal_number}</td>
                      <td className="p-3">
                        {readOnly ? row.description : (
                          <input
                            className="border rounded p-1 text-sm w-48 dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.description}
                            onBlur={(e) => setFieldOverride("bug_reports", row.row, "description", e.target.value)}
                          />
                        )}
                      </td>
                      <td className="p-3">
                        {readOnly ? row.severity : (
                          <select
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.severity}
                            onChange={(e) => setFieldOverride("bug_reports", row.row, "severity", e.target.value)}
                          >
                            <option value="low">low</option>
                            <option value="medium">medium</option>
                            <option value="high">high</option>
                          </select>
                        )}
                      </td>
                      <td className="p-3">{row.route}</td>
                      <td className="p-3">
                        {readOnly ? row.status : (
                          <select
                            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                            defaultValue={row.status}
                            onChange={(e) => setFieldOverride("bug_reports", row.row, "status", e.target.value)}
                          >
                            <option value="open">open</option>
                            <option value="in_progress">in_progress</option>
                            <option value="resolved">resolved</option>
                          </select>
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
                              value={currentSelection("bug_reports", row)}
                              onChange={(e) => setRowAction("bug_reports", row.row, e.target.value)}
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

Run: `cd frontend && npx vitest run src/pages/ImportSessionReviewPage.test.tsx`
Expected: PASS (full file — confirms no regression to the other ~25 tests in it).

- [ ] **Step 7: Run the full frontend typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/ImportSessionReviewPage.tsx frontend/src/pages/ImportSessionReviewPage.test.tsx
git commit -m "feat: review system_settings and bug_reports rows in the import session UI"
```

---

### Task 7: `ניקוד` help tab

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx`
- Modify: `frontend/src/components/HelpModal.test.tsx`

**Interfaces:**
- Consumes: `listDutyTypes(): Promise<DutyType[]>` from `../api/dutyConfig` (existing;
  `DutyType` has `id, name, score_per_day: string, description: string | null, active: boolean`).

- [ ] **Step 1: Write the failing tests**

In `frontend/src/components/HelpModal.test.tsx`, add a mock for the duty-config API next to
the existing `vi.mock("../api/scoring", ...)` line:

```typescript
vi.mock("../api/dutyConfig", () => ({ listDutyTypes: vi.fn() }));
```

Add these tests (find the existing `render(<HelpModal onClose={...} />)` pattern used by
other tests in this file and match it):

```typescript
it("shows the scoring tab to a plain soldier", () => {
  setUser("soldier");
  render(<HelpModal onClose={() => {}} />);
  expect(screen.getByText("🏅 ניקוד")).toBeInTheDocument();
});

it("scoring tab lists duty types with their score_per_day", async () => {
  setUser("soldier");
  const { listDutyTypes } = await import("../api/dutyConfig");
  (listDutyTypes as ReturnType<typeof vi.fn>).mockResolvedValue([
    { id: "1", name: "שמירה", score_per_day: "1.50", description: "שמירה בשער", active: true },
    { id: "2", name: "ישן", score_per_day: "0.50", description: null, active: false },
  ]);
  render(<HelpModal onClose={() => {}} initialTab="scoring" />);
  expect(await screen.findByText("שמירה")).toBeInTheDocument();
  expect(screen.getByText("1.50")).toBeInTheDocument();
  expect(screen.getByText("ישן")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/HelpModal.test.tsx -t "scoring"`
Expected: FAIL — text "🏅 ניקוד" not found (tab doesn't exist yet).

- [ ] **Step 3: Add the `ScoringTab` component**

In `frontend/src/components/HelpModal.tsx`, add the import:

```typescript
import { DutyType, listDutyTypes } from "../api/dutyConfig";
```

Add the component right before `function FairnessTab()`:

```typescript
function ScoringTab() {
  const [dutyTypes, setDutyTypes] = useState<DutyType[]>([]);

  useEffect(() => {
    listDutyTypes().then(setDutyTypes).catch(() => setDutyTypes([]));
  }, []);

  return (
    <div className="space-y-4 text-sm leading-relaxed" dir="rtl">
      <h3 className="text-base font-semibold text-indigo-700 dark:text-indigo-300">מה זה ניקוד?</h3>
      <p className="text-gray-700 dark:text-gray-300">
        לכל סוג תורנות יש <strong>ניקוד ליום</strong> (score_per_day) — כמה &quot;שווה&quot; יום אחד
        של אותה תורנות. ניקוד התורנות עצמה הוא הניקוד ליום כפול מספר הימים שלה:
      </p>

      <div className="bg-indigo-50 dark:bg-indigo-950 rounded-xl p-4 border border-indigo-200 dark:border-indigo-800 space-y-2">
        <p className="font-medium text-indigo-800 dark:text-indigo-200 font-mono text-xs">
          ניקוד התורנות = ניקוד ליום × מספר ימים
        </p>
        <p className="text-indigo-700 dark:text-indigo-300 text-xs">
          לדוגמה: תורנות &quot;שמירה&quot; עם ניקוד ליום 1.5, שאורכה יומיים, שווה 1.5 × 2 = 3.0 נקודות.
        </p>
      </div>

      <p className="text-gray-700 dark:text-gray-300">
        להלן סוגי התורנות המוגדרים כרגע במערכת וניקוד היום שלהם:
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="border-b dark:border-gray-600 text-gray-500 dark:text-gray-400">
              <th className="text-right py-1 pr-2 font-medium">סוג תורנות</th>
              <th className="text-right py-1 pr-2 font-medium">ניקוד ליום</th>
              <th className="text-right py-1 font-medium">תיאור</th>
            </tr>
          </thead>
          <tbody>
            {dutyTypes.map((dt) => (
              <tr
                key={dt.id}
                className={`border-b border-gray-100 dark:border-gray-700 ${dt.active ? "" : "opacity-50"}`}
              >
                <td className="py-1.5 pr-2 font-medium text-gray-800 dark:text-gray-200">{dt.name}</td>
                <td className="py-1.5 pr-2 font-mono text-indigo-700 dark:text-indigo-300">{dt.score_per_day}</td>
                <td className="py-1.5 text-gray-600 dark:text-gray-300">{dt.description ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 rounded-lg p-3 text-xs text-amber-800 dark:text-amber-300">
        📌 הניקוד שנצבר מכל התורנויות משמש לחישוב העומס הרבעוני שלך, שקובע את סדר העדיפויות
        בשיבוץ הבא — ראו טאב &quot;⚖️ הוגנות ושקיפות&quot; להסבר המלא.
      </div>
    </div>
  );
}
```

Add the tab definition to `TAB_DEFS`, right after the `algorithm` entry:

```typescript
  { id: "scoring", label: "🏅 ניקוד", visible: (u) => authenticated(u) },
```

Add the render branch in the modal's tab content area, right after
`{activeTab === "algorithm" && <AlgorithmTab user={user as PermissionUser | null} />}`:

```typescript
          {activeTab === "scoring" && <ScoringTab />}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/HelpModal.test.tsx`
Expected: PASS (full file — confirms no regression to existing tab-visibility tests).

- [ ] **Step 5: Run the full frontend typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/HelpModal.tsx frontend/src/components/HelpModal.test.tsx
git commit -m "feat: add ניקוד help tab with live duty-types table"
```

---

## Final verification (manual, after all tasks)

1. Run the full backend suite: `cd backend && pytest -q` (fast suite; run `pytest --slow -q`
   only if preparing a release, per project convention).
2. Run the full frontend suite: `cd frontend && npm test`.
3. Start the dev stack (`.\dev.ps1`), go to `/planning/export`, check "הגדרות מערכת" and
   "דוחות תקלות", export, open the file and confirm both sheets are present with real data.
4. Edit one setting value and one bug report's status in the downloaded file, go to
   `/import/upload`, upload it, confirm the review page shows both new tabs with the edited
   rows, confirm the session, and verify the change landed (setting value changed in
   `/system-settings`, bug report status changed in the admin bug reports tab).
5. Open the help modal (❓) as a regular soldier account and confirm the "🏅 ניקוד" tab shows
   the live duty-types table.
