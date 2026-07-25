# Bug Report Feature — Design

## Overview

A user-facing bug-report mechanism: a "מצאתי באג" bug icon in the header (clickable
even when other modals are open) opens a modal that captures a screenshot of the
current page, lets the user describe the issue and pick a severity, and submits it
along with server-attached context (user details, recent audit-log actions, recent
in-app navigation history). Reports are persisted to the DB and always mirrored to a
JSON file on disk as a durability fallback. Admins review reports in a new tab under
System Settings.

## Architecture & Data Flow

The bug-report trigger is mounted once, at the `Layout` level, and rendered via a
React `createPortal` into `document.body` so it sits outside every other modal's DOM
subtree and stacking context (`z-[100]`). This is the first portal usage in the
codebase; existing modals are all inline `fixed inset-0` overlays with no portal, so
this keeps the trigger clickable regardless of what else is open.

Flow:
1. User clicks the bug icon.
2. Frontend captures a screenshot of the current page via `html-to-image`
   (`toPng(document.body)`), reads the current route, and reads the in-memory
   navigation-history ring buffer.
3. `BugReportModal` opens showing the screenshot thumbnail, a free-text box, and a
   3-button severity picker (נמוכה / בינונית / גבוהה).
4. On submit, the frontend POSTs `{description, severity, screenshot, route,
   nav_history}` to the backend. The frontend does **not** gather user details or
   audit-log data itself — the backend attaches those server-side using the
   authenticated session, since the audit log isn't otherwise exposed to the
   frontend and server-attached data is more trustworthy than client-supplied data.
5. Backend writes a JSON file to `{LOG_DIR}/bug_reports/{id}_{timestamp}.json`
   **first** (reusing the same `LOG_DIR`-resolution logic as
   `backend/app/logging_config.py`, so this stays consistent with the Docker
   deployment's `/app/logs` mount rather than a hardcoded repo-root path), then
   attempts a DB insert. If the DB insert fails, the JSON file is still on disk
   and the endpoint still reports success to the user; the DB failure is logged
   server-side. If both writes fail, the endpoint returns a real error.
6. Frontend shows a success toast and closes the modal.

Bug reports are fire-and-forget from the submitter's perspective — no "my reports"
view for regular users, only a success confirmation.

## Frontend Components

- **`frontend/src/components/BugReportTrigger.tsx`** — portal-mounted header icon
  (lucide-react `Bug`, `size={22}`, `aria-label="מצאתי באג"`, styled like other header
  icons: `text-gray-500 hover:text-indigo-600`) plus its own open/closed modal state.
  Mounted once inside `Layout.tsx`.
- **`frontend/src/components/BugReportModal.tsx`** — the report form: screenshot
  preview (captured on open), description textarea, severity picker, submit/cancel.
  Rendered at `z-[100]`+ so it stacks above any other open modal. Shows a loading
  state while the screenshot is being captured.
- **`frontend/src/hooks/useNavigationHistory.ts`** — context/hook using
  `useLocation` from `react-router-dom`, pushing `{path, timestamp}` into an
  in-memory ring buffer (last 15 entries), provided at app root. Resets on full page
  reload by design — no persistence.
- **`frontend/src/api/bugReports.ts`** — typed fetch wrapper:
  `submitBugReport(payload)` (any authenticated user), and admin-only
  `listBugReports(filters)`, `getBugReportJson(id)`, `updateBugReportStatus(id,
  status)`.

Dependency: add `html-to-image` to `frontend/package.json`.

## Backend

### Model

New `BugReport` table in `backend/app/db/models.py`:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `reporter_id` | UUID FK → `soldiers.id` | |
| `description` | text | capped at 2000 chars, enforced in the Pydantic request schema |
| `severity` | enum: `low` / `medium` / `high` | |
| `status` | enum: `open` / `in_progress` / `resolved` | default `open` |
| `screenshot` | `LargeBinary`, nullable | raw PNG bytes, not base64 — matches the existing upload pattern (`ExemptionRequestFile`, `GimelimAttachment` both use `LargeBinary`); null if client-side capture failed. Frontend downsizes/caps the PNG before upload (e.g. clamp to viewport dimensions) so one report can't blow past request-size limits. |
| `route` | str | page the report was filed from |
| `nav_history` | JSONB | recent route visits |
| `audit_snapshot` | JSONB | last 20 `AuditLog` rows for this user, captured at submit time |
| `user_snapshot` | JSONB | reporter's name/rank/role/id at time of filing (survives later user changes) |
| `json_file_path` | str, nullable | path to the mirrored JSON file; null if the JSON write failed but the DB insert still succeeded |
| `created_at` / `updated_at` | timestamp | |

Retention: rows and mirrored JSON files (which contain PII — screenshots, audit-log
entries, user snapshots) are kept indefinitely; no automatic cleanup job is in scope
for this feature.

New Alembic migration for this table.

### Routes (`backend/app/routes/bug_reports.py`)

- `POST /bug-reports` (any authenticated user) — builds the record, queries
  `AuditLog` where `actor_id == user.id` ordered by `created_at desc` limit 20,
  writes the JSON file, then attempts the DB insert per the error-handling rules
  above.
- `GET /admin/bug-reports` (admin only, `require_roles("admin")`) — paginated
  (`limit`/`offset` `Query` params, same pattern as `algorithm.py`'s and
  `notifications.py`'s existing list endpoints — no new pagination pattern needed),
  filterable by `severity` and `status`.
- `GET /admin/bug-reports/{id}/json` (admin only) — returns the raw JSON file
  content, for the admin "view JSON" option.
- `PATCH /admin/bug-reports/{id}` (admin only) — update `status`.

### Service (`backend/app/services/bug_reports.py`)

Holds the JSON-write + audit-query + DB-write orchestration, keeping the route thin.

## Admin UI

`frontend/src/pages/admin/BugReportsContent.tsx`, added as a 4th tab
("דיווחי באגים") in `AdminSettingsPage.tsx` (`TabBar` tabs array extended, bound
check `raw >= 0 && raw <= 2` becomes `<= 3`).

Table columns: date, reporter, severity (colored badge), status (editable dropdown,
calls `updateBugReportStatus`), short description preview. Rows expand inline to
show: full description, screenshot (`<img>`), nav history list, audit snapshot list,
user snapshot, and a "view JSON" toggle that fetches and pretty-prints the raw file
via `getBugReportJson`. Filter bar for severity/status; simple offset/limit
pagination controls matching the backend's existing `limit`/`offset` convention.

## Error Handling

- Screenshot capture failure (e.g. CORS/tainted canvas) → submission proceeds
  without a screenshot; non-fatal.
- JSON write failure (disk/permissions) → logged server-side; DB write is still
  attempted.
- Both JSON and DB write fail → return a real error to the user rather than a false
  success.
- DB write fails but JSON succeeded → still return success (report is durably on
  disk); log the DB error server-side for follow-up.

## Testing

- Backend: JSON file is always written on a successful submit; DB failure still
  leaves the JSON file and returns success; admin-only enforcement on the three
  admin endpoints; status update persists.
- Frontend: vitest unit tests for `useNavigationHistory`'s ring-buffer behavior and
  the severity picker. Screenshot pixel output is not tested.
