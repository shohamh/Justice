# Agentic Bug-Report Markdown Export

## Goal

Add an admin-only download named `ייצוא לMarkdown לטובת טיפול אייג'נטי` that exports active bug reports into an offline ZIP containing an index, one Markdown file per report, and all available images linked from the Markdown.

## Scope and selection

- The default export includes every report with status `open` or `in_progress`.
- The optional filtered export applies the admin table's severity filter and active-status filter.
- `resolved` and `wont_fix` are excluded in both modes, including when supplied manually to the endpoint.
- Pagination never limits either export.
- A zero-match export is valid and contains an explanatory `index.md`.

## Archive contract

```text
bug-reports-YYYY-MM-DD-HHmm.zip
├── index.md
├── reports/
│   ├── <report-id>.md
│   └── ...
└── images/
    └── <report-id>/
        ├── original-screenshot.png
        └── comment-<comment-id>-<n>.<ext>
```

`index.md` lists the export timestamp, scope, count, and newest-first report links. Each report file includes triage metadata, user description, route, navigation history, user/audit snapshots, original screenshot, and chronologically ordered comments with attachment links. Relative links must work when the ZIP is extracted or opened by an agent.

Sensitive data currently stored in the report is intentionally retained. Missing image bytes are represented inline in the report Markdown with a clear Hebrew notice; no separate warnings file is created.

## API and UI

The backend exposes an authenticated `GET /api/admin/bug-reports/export` endpoint:

- `scope=all_active` is the default.
- `scope=filtered` accepts `severity=low|medium|high` and `status=open|in_progress`.
- The endpoint returns a timestamped ZIP attachment and never changes report state.

The existing admin bug-report table gets the named export control with two choices: all active reports (default) and current filters. The UI passes only severity and active status for filtered exports, disables the control during download, and displays a translated error on failure.

## Architecture

The server owns selection, Markdown generation, image packaging, and ZIP creation. A focused export service keeps archive formatting testable independently from FastAPI and the existing table. No database migration or new persistent export job is needed.

## Verification

Backend tests cover selection, exclusion, filter semantics, Markdown links, comments, attachments, missing images, empty archives, safe paths, authorization, response headers, and read-only behavior. Frontend tests cover both export scopes, current-filter propagation, pagination exclusion, busy state, and download errors.
