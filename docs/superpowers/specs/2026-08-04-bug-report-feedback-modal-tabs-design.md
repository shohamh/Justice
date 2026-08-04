# Bug Report Feedback Modal Tabs — Design

## Context

The feedback flow currently has two separate surfaces:
- A floating "מצאתי באג" (found a bug) trigger button, rendered globally via
  `BugReportTrigger.tsx` inside `Layout`, which opens `BugReportModal` — a
  single-purpose "submit a new report" form.
- A `/my-bug-reports` page (`MyBugReportsPage.tsx`), linked from the profile
  page and from "My Requests," listing the reporter's own bug reports with
  an expandable inline comments panel (`BugReportCommentsPanel`) per report.
  Notifications for new replies deep-link here via
  `/my-bug-reports?report=<id>`.

This spec merges the second surface into the first: the floating button
becomes the single entry point for both submitting new feedback and
reviewing/replying to the reporter's own past reports, via a two-tab modal.
It also adds unseen-activity badges (report replies or status changes) on
both the trigger button and the modal's second tab, with a precise
read/unread tracking mechanism that did not exist before.

## Goals

- One floating button opens a modal with two tabs: "דיווח חדש" (new
  feedback, default) and "הדיווחים שלי" (my reports).
- The "my reports" tab reuses the existing list/expand/comments UI logic
  currently in `MyBugReportsPage.tsx`.
- A badge on the "my reports" tab and on the floating trigger button shows
  the count of the reporter's own bug reports that have unseen activity
  (a new reply, or a status change) since the reporter last viewed them.
- The badge count decreases per-report, precisely when the reporter expands
  that report's thread (or posts a reply to it themselves) — not merely by
  opening the tab or the modal.
- Clicking a `bug_report`-type notification opens the modal directly on the
  "my reports" tab with that report expanded, from anywhere in the app —
  no route navigation.
- The old `/my-bug-reports` route, its page component, and both links to it
  (profile page, "My Requests" page) are removed.

## Non-goals

- No change to admin-side bug report review (the admin table, its badges,
  filters, and inline comments stay as they are).
- No new notification type or delivery channel — only how a *reporter's*
  own view tracks "seen" state.
- No change to the existing screenshot-capture flow when opening via the
  trigger button.

## Architecture

### Frontend: shared modal state via context

A new `BugReportModalProvider` (in `frontend/src/contexts/`) follows the
existing `SoldierModalContext` pattern already used in this codebase: a
context provider that owns modal open/closed state, wraps the app once at
the `App.tsx` level (alongside `SoldierModalProvider`), and is unaffected by
`Layout` remounting on every page navigation (each page renders its own
`<Layout>`, so any state living inside `Layout` or its children does not
survive navigation — the provider must sit above the `<Routes>` tree).

```ts
interface BugReportModalContextValue {
  openBugReportModal: (opts?: {
    tab?: "new" | "mine";
    reportId?: string;
    screenshot?: string | null;
  }) => void;
}
```

- Default `tab` is `"new"` when omitted (covers the trigger-button flow,
  which always opens fresh).
- `reportId` (only meaningful with `tab: "mine"`) marks which report should
  be expanded once the "my reports" list has loaded — same "may not match
  any row, and that's fine" semantics the old `MyBugReportsPage.tsx` already
  had for its `?report=` query param.
- The provider renders `<BugReportModal>` when open; closing clears state.

### `BugReportTrigger.tsx`

Unchanged capture logic (mousedown-triggered screenshot capture with the
6s timeout). Instead of local `open`/`screenshot` state driving its own
`<BugReportModal>` render, it calls
`openBugReportModal({ tab: "new", screenshot })` from the context on
completion. The badge (see below) renders on this button the same way
`NotificationBell` renders its unread count.

### `BugReportModal.tsx` — tabbed restructure

The modal dialog chrome (overlay, header, close button, backdrop/keyboard
close via `useModalBackClose`) stays as-is. Below the header, two tab
buttons:

- **"דיווח חדש"** — today's existing form (description, severity picker,
  screenshot preview, submit). Behavior identical to today; on success,
  same 1.2s-delay auto-close.
- **"הדיווחים שלי"** — the list+expand UI moved from `MyBugReportsPage.tsx`:
  fetches `getMyBugReports()`, renders each report with severity/status
  badges and description, and expands into `BugReportCommentsPanel` on
  click. A badge on this tab label shows the unseen-activity count (see
  below). When the modal opens with `tab: "mine"` and a `reportId`, that
  report is expanded automatically, same re-sync-on-change behavior the old
  page had (a `useEffect` keyed on the requested report id, since the modal
  instance can be re-triggered with a different `reportId` by a second
  notification click without necessarily unmounting).

Which tab is active is local `useState` inside `BugReportModal`, seeded
from the `tab` the provider was opened with; switching tabs manually is a
plain click, no navigation involved.

### Backend: "seen" tracking on `bug_reports`

New nullable column: `reporter_last_seen_at: datetime | None` on
`BugReport`. Migration follows the existing additive-column pattern in this
codebase (see e.g. the `bug_report_comment` notification-type migration for
alembic conventions).

A report has **unseen activity** when either of these holds:

```
unseen_comment = last_comment_at IS NOT NULL
                 AND (reporter_last_seen_at IS NULL OR last_comment_at > reporter_last_seen_at)

unseen_status  = updated_at > created_at
                 AND (reporter_last_seen_at IS NULL OR updated_at > reporter_last_seen_at)

has_unseen_activity = unseen_comment OR unseen_status
```

`last_comment_at` is the existing aggregate (max `BugReportComment.created_at`
per report) already computed by `_comment_aggregates_subquery()`.
`updated_at` is already bumped by `update_bug_report_status` and *not* by
comment creation, so `updated_at > created_at` cleanly means "the status
was changed at least once" without needing to special-case the initial
`open` status or track prior values.

**Self-comments don't count as unseen for the author.** When
`create_bug_report_comment` runs and `comment.author_id == report.reporter_id`
(the reporter replying in their own thread), the same request also sets
`report.reporter_last_seen_at = comment.created_at`. This keeps the
invariant simple: `reporter_last_seen_at` only ever needs comparing against
`last_comment_at`/`updated_at` with no author-filtering logic required at
read time.

### New endpoints

- **`POST /bug-reports/{report_id}/seen`** — reporter-or-admin gated (reuse
  `_require_reporter_or_admin`, consistent with the comments endpoints even
  though only the reporter's own client will call this in practice). Sets
  `reporter_last_seen_at = now()` and commits. No response body beyond 204,
  or a trivial ack — frontend doesn't need the updated report back since it
  already has it client-side.
- **`GET /my/bug-reports/unseen-count`** — returns `{count: number}`,
  the number of the caller's own bug reports with `has_unseen_activity`
  true. Polled by the frontend every 30s, same interval and pattern as
  `getUnreadCount()` in `api/notifications.ts` / `NotificationBell.tsx`.

### `BugReportSummaryOut` change

Add `has_unseen_activity: bool` to the shared summary schema, computed via
the SQL expression above **only** in `list_my_bug_reports` (the reporter's
own listing) — the admin listing (`list_bug_reports`) always returns
`False` for this field, since seen/unseen is a reporter-specific concept
with no meaning for an admin browsing all reports. `_summary_out` /
`_summary_with_comment_aggregates` take the computed value as a parameter
with a `False` default so the admin call site doesn't need to change beyond
its existing call shape.

### Notification click handling

`getNotificationLink()` (the shared helper in `frontend/src/api/notifications.ts`
introduced during the last bug-report change) currently returns a URL
string for every reference type, including `bug_report` →
`/my-bug-reports?report=<id>`. Since that route is being removed, `bug_report`
notifications can no longer be handled by "return a link, then navigate."

`NotificationBell.tsx` and `NotificationsPage.tsx` both special-case
`reference_type === "bug_report"`: instead of calling
`navigate(getNotificationLink(n))`, they call
`openBugReportModal({ tab: "mine", reportId: n.reference_id })` (via the new
context) and skip navigation entirely — the notification's own mark-read
behavior on click is unchanged. All other reference types continue through
the existing `getNotificationLink()` + `navigate()` path unchanged.

### Removals

- `frontend/src/pages/MyBugReportsPage.tsx` and its test file — deleted;
  logic lives in `BugReportModal`'s "mine" tab instead.
- `/my-bug-reports` route in `App.tsx` — deleted.
- `profile.my_bug_reports` link block in `ProfilePage.tsx` — deleted.
- The "my-requests-bug-reports-link" block in `MyRequestsPage.tsx` (added
  in the prior bug-report change) — deleted; no replacement link, per
  explicit instruction that the modal is now the only entry point.

## Testing

- **Backend:** unit/integration tests for `POST /bug-reports/{id}/seen`
  (reporter can mark seen, non-reporter/non-admin gets 403), the
  unseen-activity SQL logic (a report with a comment from someone else is
  unseen; a report whose only comment is the reporter's own is not; a
  report whose status changed and hasn't been seen since is unseen; marking
  seen clears both conditions), and `GET /my/bug-reports/unseen-count`
  (correct count across a mix of seen/unseen reports, scoped to the caller
  only).
- **Frontend:** `BugReportModalContext` tests (or covered via the modal's
  own tests) for tab switching and reportId-driven auto-expand;
  `BugReportModal.test.tsx` extended with "my reports" tab behavior
  (loading/empty/list/expand, matching what `MyBugReportsPage.test.tsx`
  covered); `BugReportTrigger.test.tsx` updated for opening via context
  instead of local state, plus badge rendering; `NotificationBell.test.tsx`
  / `NotificationsPage.test.tsx` updated so a `bug_report` notification
  click opens the modal (assert the context call / modal presence) instead
  of asserting a `navigate()` call; `ProfilePage.test.tsx` /
  `MyRequestsPage.test.tsx` updated to assert the removed links are gone.

## Open risk / judgment calls made here

- `reporter_last_seen_at` is deliberately per-report, not per-comment —
  matches "the reporting user has read the replies" read literally as
  "viewed the thread," not "acknowledged every individual message."
- The unseen badge is scoped entirely to the reporter's own view; there is
  no equivalent "someone replied to a bug report" signal surfaced to admins
  beyond what already exists (the admin table's own comment-count/
  latest-response columns from the prior feature).
