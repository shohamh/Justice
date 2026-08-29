# Admin Error Inbox Design

## Goal

Give administrators a useful, Hebrew-localized error inbox with durable per-admin unread state, date/time filtering, and safe log cleanup.

## Behavior

- The admin settings page has an Errors tab beside Bug Reports.
- Error entries show source, timestamp, request ID, message, and expandable structured details. Frontend records include browser URL, user agent, error kind, stack, request data, response data, and correlation ID where available.
- Errors can be filtered by source and an inclusive local date/time range. The backend receives ISO-8601 UTC bounds and performs the filtering before pagination.
- An administrator can clear all error entries at or before a selected timestamp. The operation requires confirmation, rewrites both current and rotated error logs atomically per file, and does not alter ordinary `backend.log`.
- Error unread state is tracked per admin in the database. New backend/frontend log entries are unread until that admin reads them. Opening the Errors tab marks the entries loaded for that view as read.
- Bug-report unread state is also tracked per admin. Opening the Bug Reports tab marks the loaded reports as read, while new reports or later activity become unread again.
- The system-settings top navigation badge equals unread errors plus unread bug reports for the current admin. The Errors tab badge equals unread errors.
- All new labels, controls, confirmations, empty states, and errors are translated to Hebrew.

## Security and data handling

- Error listing, unread state, and clearing are restricted to `admin` role through the existing authorization dependency.
- Existing redaction remains in force. The UI renders details as escaped JSON and does not provide raw file access.
- Clear accepts only a validated timestamp and returns the number of removed records. It never accepts an arbitrary path.

## Architecture

- Keep log records file-backed and add a small `admin_error_reads` persistence model keyed by `(admin_id, source, record_identity)`; record identity is a stable hash of source, timestamp, request ID, message, and serialized record. This preserves unread state across pagination and process restarts without copying tracebacks into the database.
- Add a backend error-log service responsible for parsing, UTC range filtering, pagination, stable identities, unread counts, and atomic clear-through rewriting.
- Expose admin endpoints for listing errors, unread summary, marking error identities read, and clear-through. Extend the existing admin bug-report API with a per-admin unread count/mark-read operation if the current model does not already provide the required semantics.
- Extend the frontend bug-report API module and admin page. Use React Query for list/count invalidation and the existing `TabBar`/navigation badge patterns.

## Acceptance criteria

1. An admin sees complete frontend error context, not only the short message.
2. Hebrew labels are shown throughout the Errors tab.
3. Date/time range filters affect the returned total and rows.
4. Clear-through removes only matching error records and leaves later records intact.
5. Two admins have independent unread counts.
6. Reading errors decreases both the Errors tab badge and the settings navigation badge; new records increase them again.
7. Non-admins receive the existing authorization response for every new endpoint.
