# Excel import/export for system settings & bug reports, plus a ניקוד help tab

## Context

The app has two working Excel pipelines today:

- **Export**: `frontend/src/pages/planning/ExportPage.tsx` (route `/planning/export`) —
  checkbox UI that fetches `GET /config/export?sheets=...` (structural/config
  sheets: `duty_types`, `duty_locations`, `hierarchy`, `exemption_types`) and
  `GET /import/export?sheets=...` (transactional sheets: `soldiers`,
  `duty_shifts`, `assignments`, `shift_templates`), merges the two workbooks
  client-side, and downloads one `.xlsx`.
- **Import**: `ImportUploadPage.tsx` → `POST /import/sessions` → parsed by
  `app/services/import_parsers/v1_standard.py` into a `ParsedImportData`
  object → reviewed on `ImportSessionReviewPage.tsx` → applied by
  `confirm_session()` in `app/services/import_sessions.py`, which already
  creates/updates `duty_types`, `hierarchy`, and `exemption_types` (this was
  previously assumed broken; it isn't — the old `/import/preview` +
  `/import/apply` pair in `import_excel.py` is dead code, unused by any
  frontend page, and is not being touched by this work).

Two entities are missing from this pipeline entirely:

- **System settings** — round-trips today only as JSON, via
  `SystemSettingsPage.tsx`'s `handleExport`/`handleImportFileChange` and
  `GET/POST /admin/system-settings/export`/`import`.
- **Bug reports** — has JSON *import* only (`POST /admin/bug-reports/import`,
  for the screenshot-mirror workflow used when restoring reports from disk),
  no export at all.

Separately, there's no help content anywhere explaining what "ניקוד" (score)
means or listing the duty types and their `score_per_day` values. The app
already has a tabbed `HelpModal.tsx` (`🔄 החלפות`, `⚙️ האלגוריתם`, `⚖️ הוגנות
ושקיפות`, `🔬 מאחורי הקלעים`, etc.) — this is the established pattern for
"explain a concept to the user," so the new content is a new tab there, not a
standalone page.

## Goals

1. `system_settings` becomes a sheet in the unified export (`ExportPage.tsx`)
   and a sheet the import-session pipeline can parse and apply.
2. `bug_reports` becomes a sheet in the unified export and import pipeline,
   with the JSONB snapshot fields included as JSON text (screenshots excluded
   — binary doesn't belong in a spreadsheet cell; still reachable via the
   existing per-report screenshot endpoint).
3. A new `ניקוד` tab in `HelpModal.tsx`, visible to all authenticated users,
   showing a live duty-types table and an explanation of the score model.

## Non-goals

- No changes to the existing JSON export/import paths for settings or bug
  reports — Excel is additive, not a replacement.
- No changes to `duty_types` / `hierarchy` / `exemption_types` / `duty_locations`
  import — already works via the session pipeline.
- No deletion of the dead `import_excel.py` `/preview` + `/apply` endpoints in
  this change (out of scope; flagged, not touched).
- The `ניקוד` tab explains `score_per_day` and `block_score`, not the full
  quarterly fairness/effort_score math — that's already covered by the
  existing `⚖️ הוגנות ושקיפות` tab, which the new tab links to rather than
  duplicating.

## Design

### 1. System settings sheet

**Sheet shape** — two columns, one row per setting: `key`, `value_json`
(the setting's value JSON-encoded, e.g. `8`, `true`, `"pull"`, so booleans/
numbers/strings/lists round-trip without ambiguity — a plain string column
can't distinguish `"true"` the string from `true` the boolean, or `"8"` from
`8`). Hidden keys (`system.holding_node_id`) are excluded, matching the
existing `_HIDDEN_KEYS` behavior in `system_settings.py`.

**Export** — new `_write_system_settings(wb, session)` in
`backend/app/routes/config_export.py`, added to `_WRITERS`/`ALL_SHEETS`. It
reuses the same query as `export_settings()` in `system_settings.py`
(`SELECT * FROM system_settings WHERE key NOT IN _HIDDEN_KEYS`) and writes
`key, json.dumps(value)` per row.

**Import parsing** — new `ImportSystemSettingRow(source_row, key, value_json)`
in `import_parsers/schema.py`; `"system_settings"` added to `KNOWN_SHEETS` and
parsed in `v1_standard.py` the same way other sheets are (`_sheet_rows`, skip
blank rows). `value_json` is stored as the raw cell string; JSON-decoding
happens at apply time so a malformed cell surfaces as a row-level error
instead of failing the whole parse.

**Import apply** — new block in `confirm_session()` (`import_sessions.py`),
following the existing per-sheet loop pattern (`for row in
state.get("system_settings", [])`, respecting `_effective_action` /
selections same as `duty_types`/`hierarchy`). Each row: `json.loads(value_json)`
(row error on failure), then `set_setting(session, key=row.key, value=parsed,
actor_id=actor.id)` — the same service function `PUT /admin/system-settings`
already uses, so validation/side-effects (e.g. the `telegram.enabled` →
`registration.telegram_required` cascade) stay centralized. Upsert is
inherent — `set_setting` already updates-or-creates by key.

**Frontend** — add `{ key: "system_settings", label: "הגדרות מערכת" }` to
`CONFIG_SHEET_OPTIONS` in `ExportPage.tsx` (it already fetches from
`/config/export`, no new fetch needed). `_session_summary()` in
`import_sessions.py` gets a `"system_settings": len(state.get("system_settings", []))`
row-count entry. `ImportSessionReviewPage.tsx` needs a preview section for
this sheet (key / new-value / current-value columns — simpler than the
soldier/duty-type diff views since there's no "new vs update" distinction,
just "will be set to").

### 2. Bug reports sheet

**Sheet shape** — one row per report: `id` (blank for new reports),
`reporter_personal_number`, `description`, `severity`, `route`, `status`,
`created_at`, `nav_history_json`, `audit_snapshot_json`, `user_snapshot_json`
(JSONB fields serialized with `json.dumps(..., ensure_ascii=False)`, empty
string when null). `screenshot` and `json_file_path` are excluded — binary
and a server-local path aren't spreadsheet-portable; both stay reachable via
the existing `GET /admin/bug-reports/{id}/screenshot` and `.../json`
endpoints.

**Export** — new `_write_bug_reports(wb, session)` in `config_export.py`,
added to `_WRITERS`/`ALL_SHEETS`, resolving `reporter_id` → personal number
via a `Soldier` lookup (same join pattern `_write_hierarchy` already uses for
commander/duty-manager personal numbers).

**Import parsing** — new `ImportBugReportRow(source_row, id, reporter_personal_number,
description, severity, route, status, created_at, nav_history_json,
audit_snapshot_json, user_snapshot_json)` in `schema.py`; `"bug_reports"`
added to `KNOWN_SHEETS`, parsed in `v1_standard.py`.

**Import apply** — new block in `confirm_session()`. Resolve
`reporter_personal_number` → `Soldier` (row error if not found). If `id` is
present and matches an existing `BugReport`, update
`status`/`description`/`severity`/`route` (status is the realistic bulk-edit
case — e.g. mass-closing resolved reports from a spreadsheet; the others are
updated too if changed, for symmetry with the update path other sheets use).
`reporter_id` on an existing report is never changed by an update row, even
if `reporter_personal_number` differs from the report's current reporter —
the original reporter is factual history, not an editable field; a mismatch
here is a row-level warning, not applied. If `id` is blank, create a new
`BugReport` with `json.loads()` on each JSON column (empty string → `None`,
row error on invalid JSON). No `screenshot`/`json_file_path` on create —
those stay `None`, same as any report entered outside the bug-report widget.

**Frontend** — add `{ key: "bug_reports", label: "דוחות תקלות" }` to
`CONFIG_SHEET_OPTIONS` in `ExportPage.tsx`. `_session_summary()` gets a
`"bug_reports"` count. `ImportSessionReviewPage.tsx` needs a preview section
(row / action / description / severity / status / errors — same shape as the
existing `SoldierRowPreview` table).

### 3. ניקוד help tab

New `ScoringTab()` component in `frontend/src/components/HelpModal.tsx`,
registered in `TAB_DEFS` as `{ id: "scoring", label: "🏅 ניקוד", visible:
(u) => authenticated(u) }` — placed after `algorithm` and before `fairness`,
since it explains a building block (`score_per_day` → `block_score`) that
the fairness/effort_score math (already covered in `FairnessTab`) consumes.

Content:

- **Duty types table** — fetched via the existing `listDutyTypes()` (`api/dutyConfig.ts`,
  backed by `GET /duty-types`, already open to any authenticated user via
  `require_password_changed`). Columns: name, `score_per_day`, description.
  Inactive duty types are shown but visually de-emphasized (grayed row),
  not hidden — a soldier reviewing why a type disappeared from new
  assignments should still be able to see its score.
- **Score model explanation** — plain-language walkthrough of
  `block_score = score_per_day × ימי משך` (matches
  `explain.py`'s `float(duty.score_per_day) * (duty.end_date -
  duty.start_date).days * 1000`, presented without the ×1000 milli-scaling,
  which is solver-internal), with a worked example (e.g. "תורנות שמירה,
  score_per_day=1.5, משך 2 ימים → ניקוד התורנות = 3.0"), reusing the
  `FlowStep`/example-card visual style already established in `AlgorithmTab`/
  `FairnessTab` for consistency. Closes with a short pointer: "הניקוד שנצבר
  מכל התורנויות משמש לחישוב העומס הרבעוני שלך — ראו טאב הוגנות ושקיפות."
  rather than re-explaining `effort_score`.

No backend changes needed for this tab — it's pure frontend, reusing an
existing authenticated endpoint.

## Testing

- Backend: parser test for `system_settings`/`bug_reports` sheets in
  `v1_standard.py`'s test suite; `confirm_session` apply tests (new setting,
  update existing setting, malformed `value_json` row error; new bug report,
  status-update bug report, unresolvable `reporter_personal_number` row
  error). Export writer tests for both sheets in `config_export.py`'s suite
  (marker: `misc` or wherever existing config-export tests live).
- Frontend: `ExportPage.test.tsx` — new checkboxes present, included in the
  merged workbook request. `HelpModal.test.tsx` — new tab renders, duty
  types table populates from a mocked `listDutyTypes()`.
- Manual: full round trip — export with both new sheets checked, edit a
  setting value and a bug report status in the downloaded file, re-import via
  `ImportUploadPage` → review → confirm, verify the change landed.
