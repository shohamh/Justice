# Agentic Bug-Report Markdown Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an admin-only, read-only ZIP export of active bug reports as linked Markdown and images for agent-assisted triage.

**Architecture:** A backend export service selects reports, renders Markdown, packages screenshots/comment attachments, and returns one ZIP through a new admin endpoint. The existing admin table adds a named control with all-active and current-filter modes; pagination never affects export selection.

**Tech Stack:** FastAPI, SQLAlchemy, Python `zipfile`/`io`, React, TypeScript, Vitest, pytest

**Spec:** `docs/superpowers/specs/2026-08-14-agentic-bug-report-markdown-export-design.md`

## Global Constraints

- Export only `open` and `in_progress`; always exclude `resolved` and `wont_fix`.
- Default scope is all active reports; filtered scope applies severity and active-status filters but never pagination.
- Keep existing sensitive report data in the export.
- Missing image data is documented inline in the report Markdown; do not create a warnings file.
- Export is read-only and admin-only.
- Preserve unrelated user changes, including the existing untracked backend files.

## File Map

| File | Responsibility |
|---|---|
| `backend/app/services/bug_report_export.py` | Pure archive-selection/rendering/ZIP orchestration helpers |
| `backend/app/routes/bug_reports.py` | Validated admin download endpoint |
| `backend/tests/unit/test_bug_report_export.py` | ZIP and Markdown service tests |
| `backend/tests/integration/test_bug_reports_api.py` | Endpoint authorization, query, response, and read-only tests |
| `frontend/src/api/bugReports.ts` | Browser download API helper |
| `frontend/src/pages/admin/BugReportsContent.tsx` | Export control, scope choice, busy/error state |
| `frontend/src/pages/admin/BugReportsContent.test.tsx` | Export interaction tests |
| `frontend/src/i18n/he.json` | Export labels and errors |

### Task 1: Build the export service and its failing tests

**Files:**
- Create: `backend/app/services/bug_report_export.py`
- Create: `backend/tests/unit/test_bug_report_export.py`

**Interfaces:**
- Produce `build_bug_report_export_zip(session: Session, *, scope: Literal["all_active", "filtered"], severity: str | None, status: str | None) -> bytes`.
- The service accepts ORM reports/comments/attachments through the session and returns a complete ZIP byte string.

- [ ] **Step 1: Write tests for active selection and filtered selection.**
- [ ] **Step 2: Run `python -m pytest backend/tests/unit/test_bug_report_export.py -v` and verify the tests fail because the service does not exist.**
- [ ] **Step 3: Implement a query that always filters `BugReport.status.in_(("open", "in_progress"))`, optionally filters severity, and only accepts `status` values `open` and `in_progress`.**
- [ ] **Step 4: Add tests proving `resolved` and `wont_fix` never enter either archive, including when invalid status input is passed.**
- [ ] **Step 5: Run the focused unit tests and verify selection tests pass.**

### Task 2: Render Markdown and package images

**Files:**
- Modify: `backend/app/services/bug_report_export.py`
- Modify: `backend/tests/unit/test_bug_report_export.py`

- [ ] **Step 1: Add tests that inspect ZIP members for `index.md`, per-report Markdown, original screenshots, and comment attachments.**
- [ ] **Step 2: Add tests asserting relative links from `reports/<id>.md` point to `../images/<id>/...`.**
- [ ] **Step 3: Implement stable newest-first index and per-report Markdown sections for metadata, description, screenshots, snapshots, navigation history, audit snapshot, and chronological comments.**
- [ ] **Step 4: Implement safe deterministic archive filenames using report/comment IDs and validated image extensions; never use user filenames as archive paths.**
- [ ] **Step 5: Add inline Hebrew missing-image notices when a stored screenshot/attachment cannot be packaged.**
- [ ] **Step 6: Add the zero-match `index.md` behavior and tests.**
- [ ] **Step 7: Run `python -m pytest backend/tests/unit/test_bug_report_export.py -v` and verify all service tests pass.**

### Task 3: Expose the admin download endpoint

**Files:**
- Modify: `backend/app/routes/bug_reports.py`
- Modify: `backend/tests/integration/test_bug_reports_api.py`

- [ ] **Step 1: Write endpoint tests for admin success, non-admin rejection, `all_active`, filtered severity/status, invalid status rejection, ZIP content headers, and unchanged report status/seen timestamps.**
- [ ] **Step 2: Run the focused integration tests and verify the new cases fail.**
- [ ] **Step 3: Add `GET /admin/bug-reports/export` before the parameterized report-id routes, validate `scope`, `severity`, and active-only `status`, and call the export service.**
- [ ] **Step 4: Return the bytes with `application/zip` and a timestamped `Content-Disposition` filename.**
- [ ] **Step 5: Run the focused API tests and verify they pass.**
- [ ] **Step 6: Run the existing bug-report API/service tests and verify no regressions.**

### Task 4: Add the frontend download API and UI control

**Files:**
- Modify: `frontend/src/api/bugReports.ts`
- Modify: `frontend/src/pages/admin/BugReportsContent.tsx`
- Modify: `frontend/src/pages/admin/BugReportsContent.test.tsx`
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Write Vitest tests for the API helper's default and filtered query parameters.**
- [ ] **Step 2: Add a `downloadBugReportExport` helper that requests a blob and preserves the server filename when available.**
- [ ] **Step 3: Add tests for the named control, default all-active action, filtered action using severity/status state, pagination independence, busy disabling, and translated errors.**
- [ ] **Step 4: Add the export control beside the existing JSON import control with the exact label `ייצוא לMarkdown לטובת טיפול אייג'נטי`.**
- [ ] **Step 5: Implement browser download via a temporary object URL and anchor, revoking the URL after use.**
- [ ] **Step 6: Run the focused frontend tests and `npm run typecheck`.**

### Task 5: Full verification and review

**Files:**
- No new files; inspect all touched files and the approved spec.

- [ ] **Step 1: Run backend focused tests: `python -m pytest backend/tests/unit/test_bug_report_export.py backend/tests/integration/test_bug_reports_api.py -q`.**
- [ ] **Step 2: Run frontend focused tests: `npm test -- --run src/api/bugReports.test.ts src/pages/admin/BugReportsContent.test.tsx`.**
- [ ] **Step 3: Run `npm run typecheck` and targeted ESLint on touched frontend files.**
- [ ] **Step 4: Inspect the generated ZIP in a test fixture and verify links resolve after extraction.**
- [ ] **Step 5: Review the diff against the approved spec, confirm no status mutation, and report any unrelated pre-existing failures separately.**
