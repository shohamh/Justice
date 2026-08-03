# Bug Reports Feedback and User Portal Design

## Context

The admin bug-report table currently opens comments in a modal. The comments API already authorizes both the report owner and an admin, but there is no user-facing page for a soldier to find their own reports or continue the conversation. The feedback submission modal also has a mobile layout issue that prevents scrolling and submitting.

## Goals

- Make comments part of the expanded admin row instead of a separate comments modal.
- Let each authenticated soldier view only their own bug reports and reply to them.
- Notify the report owner when another participant adds a comment, with a link directly to the relevant report.
- Improve mobile usability of the feedback submission modal.
- Make the admin table easier to scan with status labels, stronger status colors, comment counts, and sortable latest-comment timestamps.

## Non-goals

- Changing who may comment: the existing reporter-or-admin authorization remains the backend rule.
- Adding a new general-purpose messaging system.
- Notifying a user about their own comments.
- Changing the existing bug-report submission payload or screenshot capture behavior.

## Proposed architecture

### Shared comments panel

Extract the comment-listing, composer, attachment upload, retry, and error handling currently implemented by `BugReportDetailModal` into a reusable `BugReportCommentsPanel` component. The component will accept a `reportId` and render inline in both contexts:

- Admin expanded-row content, after the report metadata and JSON section, separated by a subtle top border and spacing.
- The authenticated user's bug-report page, where it remains interactive for the report owner.

The existing modal wrapper will be removed from the admin table. If no other caller needs the modal, the modal component can be deleted after its tests are migrated to the shared panel.

### Admin table summary data

Extend `BugReportSummaryOut` and the TypeScript `BugReportSummary` with:

- `comment_count: number`
- `last_comment_at: datetime | null`

The admin list query will calculate both values with one grouped/subquery-based query, preserving the existing pagination, filters, and created-date ordering. `last_comment_at` is the timestamp of the newest comment by any author. The frontend will use the ISO datetime as the sort value and display a localized Hebrew datetime, with an em dash when no comments exist.

### User bug-report page

Add a route such as `/my-bug-reports` and a page component that calls the existing `/my/bug-reports` endpoint. The endpoint already scopes results by `reporter_id == current_user.id`; add explicit backend tests that a user cannot access another user's report or comments.

The page will reuse the shared table/panel patterns but will not expose admin-only status controls, JSON import, screenshots download controls, or internal snapshots. Each row can expand to show the description, status, timestamps, and the inline comments panel. A `report` query parameter will select and expand a report when arriving from a notification.

Add a link to this page in the profile page's personal-information area.

### Comment notifications

Add a `bug_report_comment` value to `NotificationType` and the matching PostgreSQL enum migration. When a comment is created:

1. Load the report and preserve the existing reporter-or-admin authorization.
2. Create a notification for the report owner only when the comment author is not the report owner.
3. Use `reference_type="bug_report"` and `reference_id=<report id>`.
4. Route the frontend notification link to `/my-bug-reports?report=<report id>`.

The notification will use the existing notification preference, in-app, push, email, unread-count, and mark-read infrastructure. Add Hebrew translation coverage and an icon for the new notification type.

### Feedback modal mobile layout

Make the overlay safe for small viewports by using a mobile-aware vertical layout and `100dvh` constraints. The dialog will have a bounded height, an independently scrollable content area, and a footer/action area that remains reachable. Preserve backdrop-close behavior, keyboard submit behavior, disabled states, and success handling.

## Table presentation

- Render each status icon in a vertical icon-and-label control, retaining accessible labels and the current active-state indication.
- Use more distinct but light status row backgrounds for open, in-progress, resolved, and won't-fix states, with corresponding dark-mode variants.
- Add localized columns for comment count and latest response.
- Make latest response sortable using the raw datetime value rather than the localized display string.
- Keep interactive controls from triggering row expansion.

## Testing strategy

### Backend

- Summary/list tests verify comment count and latest-comment timestamp, including reports with no comments.
- User-list tests verify ownership filtering.
- Comment tests verify the owner can comment, an unrelated soldier cannot read or comment, and a comment by an admin creates exactly one owner notification.
- A comment by the owner creates no notification.
- Notification enum migration and serialization tests cover the new type and reference.

### Frontend

- Admin table tests cover status labels, row colors, comment count/latest-response rendering, datetime sorting, and inline comments without opening a modal.
- Shared comments-panel tests cover loading, sending, attachments, retry, errors, and reporter usage.
- User page tests cover own-report rendering, expansion, reply submission, query-parameter auto-expansion, and absence of admin controls.
- Notification tests cover the new translated type and navigation to the report page.
- Feedback modal tests assert the mobile-safe scroll/action structure while retaining submit behavior.

## Rollout and compatibility

The API additions are backward-compatible for existing frontend consumers. The notification enum migration must run before code paths create the new notification type. Existing comments remain available and are included in the new aggregate summary fields. No data migration is required for bug reports or comments.
