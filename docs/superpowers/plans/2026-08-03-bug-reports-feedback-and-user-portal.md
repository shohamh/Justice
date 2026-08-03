# Bug Reports Feedback and User Portal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let administrators and report owners hold inline bug-report conversations, expose only a soldier's own reports in a profile-linked page, notify owners about replies from other participants, and improve bug-report table and mobile feedback usability.

**Architecture:** Extend the existing bug-report summary endpoint with aggregate comment metadata, extract the existing comment modal body into a reusable inline comments panel, and reuse it in both admin and owner views. Add a scoped `/my-bug-reports` page and a `bug_report_comment` notification referencing the report ID, while keeping current reporter-or-admin backend authorization. Keep table sorting client-side using raw ISO timestamps and make the feedback modal's content independently scrollable on small viewports.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, PostgreSQL enum migrations, React, TypeScript, TanStack React Table, TanStack Query, Vitest, React Testing Library, pytest.

## Global Constraints

- Hebrew UI strings; English code identifiers.
- The comments rule remains reporter-or-admin; users must never receive another user's reports.
- Notify the report owner only when another participant comments; never notify for the owner's own comment.
- Preserve unrelated user WIP in the main checkout.
- Integrate through the feature branch into `dev`; do not commit directly to `dev` or `master`.

---

### Task 1: Extend bug-report summaries with comment aggregates

**Files:**
- Modify: `backend/app/routes/bug_reports.py` (`BugReportSummaryOut`, `_summary_out`, `list_bug_reports`)
- Modify: `frontend/src/api/bugReports.ts` (`BugReportSummary`)
- Test: `backend/app/routes/tests/test_bug_reports.py`
- Test: `frontend/src/pages/admin/BugReportsContent.test.tsx`

**Interfaces:**
- Produces `comment_count: int` and `last_comment_at: datetime | None` in every bug-report summary response.
- The frontend type exposes `comment_count: number` and `last_comment_at: string | null`.

- [ ] **Step 1: Write failing backend tests** for an admin list containing a report with no comments and a report with two comments, asserting count and newest timestamp.
- [ ] **Step 2: Run the focused backend tests** with `pytest backend/app/routes/tests/test_bug_reports.py -k "summary or list" -q`; confirm the response currently lacks the new fields.
- [ ] **Step 3: Add aggregate fields** using a grouped/subquery aggregate joined to the paginated bug-report query; keep severity/status filters and created-date ordering unchanged, and pass the values into `_summary_out`.
- [ ] **Step 4: Update the TypeScript summary interface** and add a frontend fixture assertion that the fields are accepted and rendered by the later table task.
- [ ] **Step 5: Run the focused backend and typecheck checks** and commit `feat: expose bug report comment aggregates`.

### Task 2: Add comment notification type and owner notification behavior

**Files:**
- Modify: `backend/app/db/models.py` (`NotificationType`)
- Create: `backend/alembic/versions/f7a8b9c0d1e2_add_bug_report_comment_notification.py`
- Modify: `backend/app/routes/bug_reports.py` (`create_bug_report_comment`)
- Modify: `backend/app/services/notifications.py` (`_FRONTEND_PATHS`)
- Modify: `frontend/src/api/notifications.ts` (icon map)
- Modify: `frontend/src/i18n/he.json`
- Modify: `frontend/src/i18n/he.test.ts`
- Test: `backend/app/routes/tests/test_bug_reports.py`
- Test: `backend/app/services/tests/test_notifications.py`

**Interfaces:**
- Adds `NotificationType.bug_report_comment` and uses `reference_type="bug_report"`, `reference_id=report.id`.
- The notification frontend route is `/my-bug-reports?report=<report id>`.

- [ ] **Step 1: Write failing backend tests** proving an admin comment creates one notification for the report owner, while the owner's own comment creates none; assert title/type/reference fields.
- [ ] **Step 2: Run those focused tests** and confirm the enum value and notification are absent.
- [ ] **Step 3: Create the PostgreSQL enum migration** with `ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'bug_report_comment'`, including the repository's downgrade convention.
- [ ] **Step 4: Add the enum value and create the notification** after the comment is committed/refreshed, only when `comment.author_id != report.reporter_id`; use the existing `create_notification` preference/push/email pipeline.
- [ ] **Step 5: Add frontend icon, Hebrew type translation, and notification path mapping**, then run backend notification tests and `npm run typecheck`.
- [ ] **Step 6: Commit** `feat: notify bug report owners about replies`.

### Task 3: Extract reusable inline comments panel

**Files:**
- Create: `frontend/src/components/BugReportCommentsPanel.tsx`
- Create: `frontend/src/components/BugReportCommentsPanel.test.tsx`
- Modify: `frontend/src/components/BugReportDetailModal.tsx` or remove it after callers are migrated
- Modify: `frontend/src/components/BugReportDetailModal.test.tsx` or migrate assertions to the panel test

**Interfaces:**
- `BugReportCommentsPanelProps = { reportId: string }`.
- The panel owns the existing query, composer, attachment upload/retry, loading, empty, and error states and uses `queryKeys.bugReportComments(reportId)`.

- [ ] **Step 1: Write failing panel tests** for loading, empty state, sending a comment, attachment retry state, and rendering an existing comment.
- [ ] **Step 2: Run the component test** and confirm the new component is missing.
- [ ] **Step 3: Move the comment logic** from `BugReportDetailModal` into the panel without changing API calls, error translations, attachment retry race protections, or query invalidation.
- [ ] **Step 4: Render the panel in the existing modal temporarily** and run the migrated modal/panel tests to prove behavior parity.
- [ ] **Step 5: Commit** `refactor: share bug report comments panel`.

### Task 4: Inline comments in admin expanded rows and improve the admin table

**Files:**
- Modify: `frontend/src/pages/admin/BugReportsContent.tsx`
- Modify: `frontend/src/pages/admin/BugReportsContent.test.tsx`
- Modify: `frontend/src/i18n/he.json` if table labels are not already present

**Interfaces:**
- Admin rows render `BugReportCommentsPanel` at the bottom of expanded content with a subtle top border/separator.
- No admin row contains a comments button that opens a modal.

- [ ] **Step 1: Add failing frontend tests** for inline comments, absence of the comments modal trigger, status labels beneath all icons, new comment-count/latest-response columns, raw-datetime sorting, and distinct row color classes.
- [ ] **Step 2: Run the focused admin test file** and confirm each new assertion fails.
- [ ] **Step 3: Replace the modal state/button** with the shared panel in expanded content; stop event propagation only for controls that must not expand the row.
- [ ] **Step 4: Render status icon plus localized label** in a compact vertical control and replace row backgrounds with stronger light/dark status colors.
- [ ] **Step 5: Add count and latest-response columns** using `comment_count`, localized `last_comment_at`, and `sortValue: report => report.last_comment_at ?? null`; display an em dash for null.
- [ ] **Step 6: Run the admin component tests and frontend lint/typecheck**, then commit `feat: improve admin bug report conversations table`.

### Task 5: Add the owner-only bug reports page and profile link

**Files:**
- Create: `frontend/src/pages/MyBugReportsPage.tsx`
- Create: `frontend/src/pages/MyBugReportsPage.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/ProfilePage.tsx`
- Modify: `frontend/src/api/bugReports.ts` if the owner API needs explicit filters/types
- Modify: `frontend/src/i18n/he.json`
- Test: `backend/app/routes/tests/test_bug_reports.py` for cross-user list/comment access

**Interfaces:**
- Route: `/my-bug-reports`.
- Query parameter: `report=<uuid>` expands that report when present.
- Uses `getMyBugReports()` and `BugReportCommentsPanel`.

- [ ] **Step 1: Write failing backend ownership tests** for two soldiers, asserting `/my/bug-reports` returns only the caller's report and `/bug-reports/{other_id}/comments` returns 403.
- [ ] **Step 2: Run the focused ownership tests** and confirm the list/comment contract needs the intended regression coverage.
- [ ] **Step 3: Write failing page tests** for own-report rendering, row expansion, reply panel, query-parameter expansion, and no admin controls/import actions.
- [ ] **Step 4: Implement the page** with `useSearchParams`, `getMyBugReports`, a compact owner table, and the shared inline comments panel; do not expose internal snapshots or admin status mutation controls.
- [ ] **Step 5: Register the route and add a profile link** in the personal-information section with Hebrew translations.
- [ ] **Step 6: Run focused page/backend tests and frontend typecheck**, then commit `feat: add personal bug reports page`.

### Task 6: Link notifications to the owner page

**Files:**
- Modify: `frontend/src/pages/NotificationsPage.tsx`
- Modify: `frontend/src/pages/MyBugReportsPage.tsx` if navigation needs a read-on-open callback
- Modify: `frontend/src/pages/NotificationsPage.test.tsx` if present, otherwise create it

**Interfaces:**
- `notificationLink("bug_report", reportId)` returns `/my-bug-reports?report=<reportId>`.

- [ ] **Step 1: Write a failing notification navigation test** for the new reference type.
- [ ] **Step 2: Run the focused notification test** and confirm the notification currently renders as non-link text.
- [ ] **Step 3: Add the link mapping** and preserve existing mark-read/delete behavior.
- [ ] **Step 4: Run notification tests and commit** `feat: link bug report notifications to reports`.

### Task 7: Fix mobile feedback modal scrolling and submission

**Files:**
- Modify: `frontend/src/components/BugReportModal.tsx`
- Modify: `frontend/src/components/BugReportModal.test.tsx`

**Interfaces:**
- Preserve `BugReportModal` props and `submitBugReport` payload.

- [ ] **Step 1: Add a regression test** that inspects the overlay/dialog/content classes and still submits through the button after a long description/screenshot state.
- [ ] **Step 2: Run the modal tests** to establish the current behavior.
- [ ] **Step 3: Apply the mobile layout**: prevent page-level overflow, constrain the dialog with `max-h-[calc(100dvh-2rem)]`, make the form content `min-h-0 overflow-y-auto`, and keep actions in a reachable footer; retain backdrop and keyboard behavior.
- [ ] **Step 4: Run modal tests, frontend lint, and typecheck**, then commit `fix: make feedback modal usable on mobile`.

### Task 8: Full verification and handoff

**Files:**
- No planned source changes; only update tests if verification exposes a directly related regression.

- [ ] **Step 1: Run focused backend bug-report tests** with the repository's supported test flags and record any Docker/shared-database limitation separately from regressions.
- [ ] **Step 2: Run frontend bug-report, comments, notifications, profile, and DataTable tests.**
- [ ] **Step 3: Run `npm run lint` and `npm run typecheck` from `frontend/`.
- [ ] **Step 4: Run `git diff --check`, inspect `git status`, and verify unrelated main-checkout WIP remains untouched.
- [ ] **Step 5: Review the branch log and prepare it for the project `merge-worktree-to-dev` workflow; do not merge or push without the user's explicit release/integration instruction.
