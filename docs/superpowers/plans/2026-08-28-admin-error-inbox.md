# Admin Error Inbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide admins with a Hebrew error inbox, date/time filtering and clear-through retention, plus persistent per-admin unread badges for errors and bug reports.

**Architecture:** Extend the existing structured JSONL error logging with a service that reads, identifies, filters, marks read, and atomically clears records. Store only per-admin read markers and bug-report read timestamps in PostgreSQL; keep tracebacks in rotating files. Expose admin-only endpoints and connect them to React Query, the existing admin `TabBar`, and `UnifiedNav`.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy/Alembic, rotating JSON logs, React, Axios, TanStack Query, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-08-28-admin-error-inbox-design.md`

## Global Constraints

- All error and bug-report reads are scoped per admin user.
- Only the existing `require_roles("admin")` dependency authorizes admin endpoints.
- Clear-through accepts a validated ISO-8601 timestamp and never arbitrary file paths.
- Existing sensitive-field redaction remains mandatory.
- Do not commit directly to `dev` or `master`; preserve the existing uncommitted logging work.

---

### Task 1: Persist per-admin unread state

**Files:**
- Create: `backend/app/db/models/admin_error_read.py` or the repository’s established model location
- Modify: `backend/app/db/models/__init__.py`
- Create: `backend/alembic/versions/<timestamp>_admin_error_reads.py`
- Test: `backend/app/db/models/tests/test_admin_error_reads.py`

- [ ] Write a failing model test proving two admins can have independent read markers for the same error identity and that duplicate `(admin_id, source, record_key)` rows are rejected.
- [ ] Run `pytest ... -v` and verify the test fails because the model/table is absent.
- [ ] Add a UUID-keyed model with admin foreign key, source, record key, and read timestamp; add a unique constraint on admin/source/record key and the migration.
- [ ] Run the focused model test and migration check; verify it passes.

### Task 2: Error-log service and admin API

**Files:**
- Modify: `backend/app/error_logs.py`
- Modify: `backend/app/routes/admin_errors.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_admin_errors.py`

- [ ] Add failing tests for UTC `from`/`to` filtering, stable record identities, unread counts, mark-read, and clear-through preserving later records.
- [ ] Add service functions with exact contracts: `read_error_logs(log_dir, source, offset, limit, from_ts=None, to_ts=None, admin_id=None)`, `get_unread_error_count(log_dir, admin_id)`, `mark_errors_read(session, admin_id, record_keys)`, and `clear_error_logs_through(log_dir, through_ts)`.
- [ ] Parse current and rotated JSONL files, ignore malformed lines, sort newest first, and atomically rewrite each affected file via a same-directory temporary file and replace.
- [ ] Extend `GET /api/admin/errors` with source/from/to filters and unread fields; add `GET /api/admin/errors/unread-count`, `POST /api/admin/errors/mark-read`, and `DELETE /api/admin/errors?through=...`, all admin-only.
- [ ] Run focused backend tests and verify all pass, including a non-admin authorization test.

### Task 3: Bug-report unread API

**Files:**
- Modify: `backend/app/routes/bug_reports.py`
- Modify: existing bug-report model/migration files only if required by the established read-state shape
- Test: `backend/app/routes/tests/test_bug_reports.py`

- [ ] Write a failing test proving each admin has a bug-report unread count, opening/marking reports read clears only that admin’s count, and a newly created report is unread again.
- [ ] Implement the smallest extension consistent with existing `seen_at` behavior: expose an admin unread count and an admin mark-read endpoint, using the persistent per-admin state from Task 1 or a narrowly scoped companion table.
- [ ] Run the focused bug-report route tests and verify non-admins remain rejected.

### Task 4: Complete frontend error context and API types

**Files:**
- Modify: `frontend/src/errorReporting.ts`
- Modify: `frontend/src/api/bugReports.ts`
- Test: `frontend/src/errorReporting.test.ts`

- [ ] Write failing tests proving HTTP 500 reports include URL, user agent, method, status, request ID, request data, response data, message, stack, and error kind, while sensitive values remain redacted.
- [ ] Add the browser context and typed admin error API methods for list, unread count, mark-read, and clear-through.
- [ ] Run the focused Vitest file and frontend typecheck.

### Task 5: Hebrew Errors tab with filters, read state, and clearing

**Files:**
- Modify: `frontend/src/pages/admin/ErrorsContent.tsx`
- Modify: `frontend/src/pages/admin/AdminSettingsPage.tsx`
- Modify: `frontend/src/i18n/he.json`
- Modify: `frontend/src/pages/admin/ErrorsContent.test.tsx`

- [ ] Add failing UI tests for Hebrew labels, date/time controls, source filtering, expanded frontend context, unread badge, marking visible records read, and confirmed clear-through.
- [ ] Implement controlled local date/time inputs converted to ISO UTC query parameters; render structured details in an accessible expandable panel; add a confirmation dialog before clear-through and refresh/invalidate affected queries after mutations.
- [ ] Add translated strings for all labels, states, errors, and confirmation text; keep the tab badge tied to the unread query.
- [ ] Run the focused UI tests and verify the Errors tab is reachable at its stable query-string index.

### Task 6: Shared settings navigation badge

**Files:**
- Modify: `frontend/src/components/UnifiedNav.tsx`
- Modify: `frontend/src/queryKeys.ts`
- Modify: `frontend/src/components/UnifiedNav.test.tsx`
- Modify: `frontend/src/pages/admin/AdminSettingsPage.tsx`

- [ ] Add failing tests proving admins see a settings badge equal to unread errors plus unread bug reports, non-admins do not, and opening the respective tabs invalidates/refreshes the badge.
- [ ] Add React Query polling/invalidation using the existing query-key conventions; render the combined badge on the system-settings link/icon while preserving existing nav layout and badge colors.
- [ ] Run focused navigation tests.

### Task 7: Integration verification and review

**Files:**
- Modify only files required by failing verification.

- [ ] Run backend focused suites, frontend lint, frontend typecheck, and frontend full tests.
- [ ] Run `git diff --check` and inspect the final diff for accidental changes, secret exposure, unsafe clear paths, and authorization gaps.
- [ ] Verify the API contract and migration from a clean database if the repository’s database test command is available.
