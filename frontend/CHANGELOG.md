# Changelog

## 2026-08-13 (3)

### Features
- Bulk export/import support for ranges (מטווחים): range locations, scheduled range days, soldier assignments/attendance, per-soldier range qualifications, and excusal requests can now be exported to Excel and re-imported through the existing import-review workflow, alongside soldiers/duty shifts/config data. Five new review tabs were added to the import-session review page, and matching checkboxes to the unified export page.

### Fixes
- The range-assignments review tab now shows the unit and lets you correct the date/type when a bulk-imported assignment doesn't match any range day, instead of only letting you skip the row.
- Approved range excusal requests now re-import correctly from an exported file (previously errored every time, since the export had no way to identify which soldier an already-approved request belonged to).
- Range excusal reasons are now masked in exports based on viewer permission, consistent with how other soldier-authored reasons (personal constraints, exemption requests) are already handled.

## 2026-08-13 (2)

### Features
- Unit-calendar info badge (planned-range coverage) now shows how many soldiers it covers, matching the warning badge; the swap-count badge gained a matching icon.

### Fixes
- Unit-calendar warning badge now catches a soldier who never had a valid qualification from the start, not just one who lost it after assignment — previously it only checked a DB flag set retroactively by a background job, so it silently missed soldiers the shift-detail modal already flagged correctly.
- Range assignment modal: the candidate pool for a range event now draws from the requesting commander/duty manager's full authorized scope instead of just the event's own hierarchy node, so the reserve list no longer dries up when that one sub-unit is full. Soldiers with a genuine hard conflict (weapons-forbidding exemption, structural ineligibility, already assigned to another range that day) are now excluded from the list entirely instead of shown greyed-out; soldiers blocked only by a personal constraint or overlapping duty stay selectable — with a conflict-warning badge — when they have a weapon-requiring duty within 30 days.
- Fixed a save failure introduced by the scope-widening above: the backend still hard-rejected a selected soldier who was outside the event's own hierarchy node even when in scope, so saving a legitimately-offered candidate could fail with a generic error. Range assignment failures now show the real reason instead of a generic message, and the error is shown next to the save button instead of the top of the modal.
- Range candidate table now shows a תעדוף column explaining why each candidate is ranked where they are, a loading placeholder instead of a misleading "no candidates" message while the list loads, and keeps its own scroll contained instead of growing the whole modal.

### Chores
- Batched the range-candidate ranking/eligibility queries (previously ~10-12 per soldier) into a fixed handful of bulk queries regardless of candidate count, fixing a real slowdown once the candidate pool widened to a manager's full scope.

## 2026-08-13

### Fixes
- Shift-modal range-eligibility warning/info badges are now click-to-open (previously a hover-only tooltip, so tapping them did nothing) and show a visible warning count on unit-calendar event tiles instead of burying the count in a hover title.
- The warning/info explanation popover is now positioned to stay within the viewport instead of overflowing outside the modal on narrow/mobile screens.

## 2026-08-12

### Features
- Range eligibility warnings: calendar events and unit-calendar tiles now show a "planned range covers this duty" badge/indicator, with notifications to the soldier, commander, and duty managers when a planned range will cover an otherwise-uncovered duty.
- New soldier-scoped range-status endpoint; a soldier's range-qualification status is now shown on their profile page and in the soldier modal, and uncovered-duty explanations are enriched with the soldier's last qualification date.
- Weapon-eligibility warnings moved from a standalone banner onto per-event calendar badges.
- Homepage אל"ל warning is now gated by structural duty-type relevance instead of an officer/career flag, and is suppressed entirely for soldiers exempt from all אל"ל duty types.
- Registration/exemptions: added a permanent-exemption toggle (disables both dates, atomic file+request submit), required medical file now enforced both client- and server-side for medical exemption rows/requests, plus registration field-level validation and invite-code rate limiting.
- Duty type settings gained a required-range-type picker.

### Fixes
- Duty assignment is never hard-blocked on a missing אל"ל qualification — the warning stays advisory only.
- Nullable `start_date` is now guarded consistently across enrollment, duty-history, export, and PATCH paths for permanent exemptions.
- Exemption requests are now returned in insertion order from registration so uploaded files correctly match their rows.
- Exemption dates are now dot-formatted; the requested node is applied on enrollment approval; the pending-exemption status label, mandatory-end/enlistment date ordering, and samal-rishon rank track were all corrected.

### Chores
- Extracted a shared exemption-file validation helper.
- Untracked `logs/backend.log.1`.
- Added design specs and implementation plans for range-eligibility warnings, permanent-exemption/medical-file requirements, and the upcoming ranges export/import feature.

## 2026-08-10 (4)

### Features
- Range detail modal: primary and reserve rosters merged with attendance actions (נכח/לא נכח) directly on each row, plus a search field to filter both lists by soldier name.
- Unit calendar duty-type filter now lists every active duty type (previously derived only from currently-loaded shifts, so a personal calendar view with no visible shifts showed an empty filter).
- Range headcount now shown on a second line under range events in the unit calendar.
- Time inputs (shifts, ranges, shift templates, duty types) now use a shared smart-mask control: typed digits progressively resolve into a valid 24h time as you type (e.g. "842" -> "8:42", "165" -> "16:50" on blur), with invalid combinations flagged in red — replacing native browser time pickers and their locale-dependent AM/PM display.
- Pending-approvals widgets (homepage and command dashboard) now include hierarchy transfer requests, previously the only one of six approval categories not surfaced there.

### Fixes
- Clicking a range in "מטווחים קרובים" now opens the range detail modal in place instead of navigating away to the ranges page.
- Today's ranges are no longer excluded from "מטווחים קרובים" (off-by-one date filter).
- Range dates now display in dd.mm.yyyy format instead of raw ISO across the upcoming-ranges widget, range detail modals, the range planning table, and the transparency table's enrollment date.
- Fixed RTL alignment of the date column in the upcoming-ranges widget.
- Duty-type calendar colors that fell in the yellow hue band are now darkened so hover highlighting no longer washes out event text against white.
- Exemptions panel now shows "(חסוי)" instead of "(0)" when the viewer lacks permission to view a soldier's exemptions, instead of looking identical to genuinely having none.
- A soldier's own profile data (e.g. an approved last-range-date field update) no longer stays stale for the rest of the session — the session now refreshes periodically instead of only at login.
- `weapon_ineligible` is now computed when an assignment is created or an algorithm proposal is accepted, instead of only being backfilled by unrelated later triggers — soldiers with no range qualifications at all now show the ineligibility warning immediately on a fresh assignment.
- Added missing i18n labels for two notification types and corrected a mislabeled reserve-shortfall notification string.

## 2026-08-10 (3)

### Fixes
- Editing a range (מטווח) with existing assignments no longer fails silently on a date/type change: the edit form now loads the full event (including assignments) so the schedule-change confirmation checkbox appears as expected, instead of the backend rejecting the save and the UI showing a generic "שמירת המטווח נכשלה" error.

## 2026-08-10 (2)

### Features
- Homepage duty widget restyled for clearer reserve/primary/called-up distinction, with called_up_from/to surfaced on effective duty spans.
- Notifications got real icon buttons, including quick approve/reject directly from swap-offer and range-excusal notifications, plus a mark-read icon (eye) distinct from approve.
- Exemption decision notifications now include the exemption type name and date range; exemption requests gained a permanent-exemption checkbox.
- Duty managers in scope are now notified when a range excusal request is pending.

### Fixes
- Swap-offer-incoming notifications route to the incoming swaps tab instead of the outgoing one.
- Homepage widget duty labels are now routed through i18n instead of hardcoded text.
- Revoking an already-expired (no-op) exemption no longer performs an unnecessary exemption-type lookup.

### Chores
- Added a nullable metadata column to Notification, with backing migration and expanded test coverage for notifications, exemptions, and range excusal.

## 2026-08-10

### Features
- Transparency page visibility rework: the "visible commander levels" multiselect is replaced by a single rank-threshold setting (minimum visible level), plus separate "levels above" thresholds for which commanders and duty managers can view the transparency page, fairness components, effort breakdown, and other soldiers' duty history. Computed live from the hierarchy, so the transparency page, fairness/effort data, and duty-history are now scoped per viewer instead of being all-or-nothing.
- The transparency page now only queries data when the current user is actually allowed to view it, and duty-history access for other soldiers follows the same visibility scope as the transparency data.
- Shifts page gained quick-filter selection by duty type and eligibility group, backed by a new eligibility-groups summary endpoint.
- Ranges/calendar pages now explain range eligibility in detail, including a dedicated commander dashboard panel listing unqualified soldiers and the reason each soldier doesn't qualify for a given range.

### Fixes
- Transparency score normalisation is now computed over the full active population (matching the previous behavior) instead of only over rows the viewer can see, and the score-adjustment preview uses the same population count.
- Closed a duty-history leak where an unrelated plain soldier could retrieve another soldier's duty history; access now requires commander/duty-manager visibility scope, with admin and event-type redaction checks preserved.
- Corrected the default transparency minimum visible level to מדור (previously every-soldier), and fixed plan/spec contradictions that documented the wrong default.
- Range warning counts are now correct and not stale, unavailable range data is distinguished from missing, and commander release/duty-detail gating was tightened.

### Chores
- Added design specs and implementation plans for the transparency/visibility permission rework and homepage/notification clarity and auto-assign scope filters.
- Removed tracked SDD scratch artifacts.
- Ignored rotated log files (`logs/*.log.*`) to keep them out of `git status` noise.

## 2026-08-09

### Features
- Added automatic weapon-ineligibility detection and caching for duty assignments, with rechecks triggered by relevant settings, duty-type, attendance, and excusal changes plus a daily safety-net worker.
- Exposed weapon-ineligibility indicators and scoped counts across navigation, calendars, shift lists, duty management, and soldier duty views, with matching notifications and administrator settings.
- Soldiers can request swaps for duties that become ineligible, and commanders can replace ineligible assignees while preserving reserve capacity and linked-reserve visibility.

### Fixes
- Corrected weapon-ineligibility cache transitions, required-range-type validation, planning-row filtering, and the audiences that can see scoped ineligibility badges.
- Fixed reserve replacement and excusal-transition behavior so assignments and reserve slots remain consistent.

### Chores
- Added database migrations, implementation documentation, and comprehensive backend/frontend coverage for weapon-ineligibility detection, visibility, replacement, and swap flows.

## 2026-08-08

### Features
- Range location is now a first-class entity: events reference a `RangeLocation` (with its own table, CRUD endpoints, and seed data) instead of free text, and the range form uses a searchable combobox with an inline add-new option.
- Weapon-qualification eligibility: duty types can declare a required range type, the scheduling algorithm now enforces the weapon-qualification constraint (toggleable per run), and the shift-assignment modal warns about weapon-ineligible candidates with matching admin settings.
- Automatic range attendance marking: a background worker marks attendance once a range event's schedule elapses, so attendance status stays current without manual entry.
- Range attendance corrections now require a reason in either direction (present→absent and absent→present), notify the soldier's direct commander, and produce a proper audit trail.
- Range assignments and removals (excusal and manual) now appear in the soldier duty-history panel with removal reasons, attribution, and a promoted-from-reserve badge; removal reasons are validated and audited server-side.
- Homepage and commander calendars now share the unit calendar component, replacing the old dashboard duty-calendar widget.

### Fixes
- Registration now validates rank against the service track live (including a discharge-date-in-the-future check), derives `is_career` and בה"ד 1 graduate status from rank instead of manual input, and adds קא"ם as a קבע-only rank.
- Range attendance statuses show proper Hebrew translations in roster rows, and the commander/approvals nav badges were colored blue.
- Various bug-report follow-ups and range/shift assignment-editing edge cases fixed (capacity validation, inline add-location form no longer submitting the range event, `as any` casts replaced with real types).
- CI now runs `app/services/tests` and resolves a `response_model` issue that blocked test collection.
- Generated temp passwords now always include at least one letter and one digit, so a freshly issued temp password can never be rejected by the app's own password policy.

### Chores
- Added design specs & implementation plans for weapon-qualification eligibility, range attendance auto-mark & corrections, ranges in duty history, the range-location entity, and the registration rank/track fix.
- Added Alembic migrations and backend/frontend test coverage for all of the above (weapon eligibility, attendance auto-mark worker, duty-history removals, range locations, required-range-type enforcement).
- Reconciled the diverged Alembic migration graph (two heads from parallel range work) with a no-op merge migration, restoring in-process test migrations.
- Aligned stale backend tests with shipped behavior (exemption submission now requires a reason, machine-readable error codes, exclusive end dates in duty-history scoring, upcoming-window shift loads) and fixed pytest 9 `pytest_plugins` collection errors — the backend suite went from 1709 collection errors to fully green.
- Added the implementation plan for ineligible-soldier visibility.

## 2026-08-06

### Features
- The swap-partner picker is now searchable.
- Bug-report screenshots and image attachments open in a fullscreen preview.
- Algorithm runs support subtree restriction, with real validation errors surfaced in the UI instead of generic messages.

### Fixes
- Duty history for swap-received duties now excludes draft/rejected assignments and correctly shows swapped-in duties for the receiving soldier.
- Fixed algorithm job settings failing to persist due to non-JSON-safe UUID serialization.
- Fixed the RTL/LTR scroll direction on the cut-off projected-effort equation.
- The algorithm run timer now ticks every second instead of following the poll cadence.
- Added missing field labels to the personal constraint request form.
- Exemption file access now shows specific permission/not-found messages instead of a generic error.
- Added a missing validation-error i18n key that was showing as a raw key in the UI.
- Fixed a crash when looking up duty history overrides for a deleted assignment.
- Dismissed duty days no longer show as active for the released soldier.
- Hierarchy-restricted announcements no longer leak to the whole organization.

### Chores
- Tightened test coverage for constraint-form field labels and bug-report comment attachment content types.

## 2026-08-05

### Features
- The unit calendar's range-type filter dropdown now stays visible whenever ranges are enabled, and calendar filters default to all-selected (with empty selection meaning "show none").
- Multi-day shifts on the calendar now get Outlook-style edge labels, including the day-of-week on each edge.

### Fixes
- Fixed multi-day shift detection and stopped multi-day shifts from rendering as duplicate per-day segments on the calendar.

## 2026-08-04

### Features
- Bug reports now support inline threaded comments with image attachments (and upload retry) for both admins and reporters; the admin table gained comment-count and latest-response columns, status icons with labels, and stronger status row colors.
- The feedback ("מצאתי באג") button now opens a two-tab modal — submit a new report, or review and reply to your own past reports — with an unseen-activity badge on the button and on replies/status changes you haven't seen yet; reply notifications now open the right report directly instead of navigating to a separate page.
- Range assignments now show and persist the reasons/capabilities behind automatic assignment choices, with matching Hebrew explanations in the UI.
- Range planning modals and the range assignment editor were reworked to match the shift-planning UI, including a shift-style assignment editor and consistent Hebrew i18n coverage.
- Ranges gained bulk actions: row-selection checkboxes, bulk clear/cancel/delete for selected ranges, and a candidate-selection panel replacing one-click auto-assign, plus a read-only ranked-candidates view and a batch-assign endpoint.
- The unit calendar's filter pills were replaced with multi-select dropdowns.

### Fixes
- Fixed the feedback (bug report) submission modal so it scrolls correctly and stays usable on mobile viewports.
- Fixed range assignment/visibility issues: draft assignments no longer leak into general lists, gating now correctly reflects range actions, and range visibility refreshes properly after changes.
- Fixed dark-mode contrast in the cancel dialog and in range modal text, added a shortcut for direct assignments, and removed a duplicate top-level key in the Hebrew translations.
- Fixed reserve promotion ranking to be preserved correctly, and resolved a diverged Alembic migration history after concurrent range work merged.
- Made the shift-style range assignment editor modal-only and fixed modal history handoff to be stack-safe across nested modals.
- Removed duplicate edit/cancel buttons and a redundant entry point from the range detail view, and made the range delete button always visible (disabled when assigned, matching shifts).

### Chores
- Added regression tests for range advance reminders, read-only range assignment controls, and cross-user bug-report comment access, and expanded frontend coverage across the bug-report and ranges UI changes.
- Documented the ranges UI parity, range-assignment-reasons, bug-report feedback modal, and ranges/shifts UI parity designs and implementation plans.
- Removed the standalone "my bug reports" page and its links now that the feedback modal covers the same flow, and removed dead range draft/confirm auto-assign code.

## 2026-08-02

### Features
- Added a shift-like Mitvachim planning board and shared UI for arranging range events and rosters.
- Added full range lifecycle controls, including roster management, editing, and cancellation.
- Added range notifications for relevant planning and assignment events.

### Fixes
- Added scoped and history guards to range workflows so actions and historical data respect authorization and lifecycle state.
- Made range seed scenarios deterministic for repeatable development and test data.
- Hardened range API startup and validation, including date-field annotation resolution, explicit node-id handling, and correct delete responses.

### Chores
- Improved backend solver-test throughput by parallelizing independent fairness scenarios and making their generated inputs deterministic.
- Added automatic-assignment regression tests and documented the range planning design and implementation.
- Stabilized date-sensitive range, attendance, roster, and constraint tests; the full backend and frontend suites now pass on the release branch.

## 2026-08-01

### Features
- Added the Mitvachim (ranges) workflow: feature-flagged range planning, scoped event and roster management, reserve assignments, attendance confirmation, no-show handling, qualification updates, score adjustments, and range visibility across the homepage, calendar, and dashboard.
- Added automatic range assignment with eligibility filtering and three-tier priority ranking, including draft rosters, shortfall reporting, quota checks, and manager confirmation/confirmation-all controls.
- Added range-specific notifications for confirmed assignments, with links to the ranges page and matching Hebrew UI coverage.

### Fixes
- Hardened range assignment workflows around draft visibility, planned-event boundaries, exclusive end dates, duplicate same-day assignments, atomic confirm-all operations, and transactional notification creation.

### Chores
- Added the database migrations and backend/frontend test coverage required for range assignments, attendance, authorization, exemptions, and auto-assignment.

## 2026-07-31

### Features
- Hierarchy transfer requests can now be approved by commanders (not just duty managers) — approving one previously failed silently with no way to complete the transfer.
- Registration and profile edits now validate that a soldier's rank is compatible with their service track (חובה/קבע), with inline validation on the registration form; the underlying rank/track compatibility table also fixed seed data that made every enlisted קבע soldier ineligible for every duty type.
- The duty-type breakdown chart (homepage and "היומן שלי") now splits days into past-served vs. future-scheduled, and the homepage visually distinguishes reserve duty assignments from primary ones with a dashed border and badge.
- Swap approval cards now show the duty type, location, and reason being swapped; duty managers/commanders are now notified when a swap request is pending their decision; the organizational-distance number next to a swap candidate is now labeled.
- Bug reports: added a "לא יטופל" (won't fix) status, a full comment thread with image attachments for both admins and reporters (with upload retry on failure), row-level status icon buttons that color the row by status, and a sortable/filterable table.
- The marketplace's unit and duty-type filters were replaced with a hierarchical tree dropdown and a checkbox-list dropdown, fixing a bug where sub-units were silently dropped from the old flat unit filter.
- List pagination (bug reports, announcements, notifications) now persists in the URL and clamps back to a valid page if a stale/out-of-range page is requested.

### Fixes
- Fixed סג"ם and קמ"א being misclassified as enlisted instead of officer ranks during registration and enrollment approval; officers are no longer automatically marked as בה"ד 1 graduates just for being officers.
- Fixed the transparency page's rank column not actually sorting senior-first by default — an earlier attempt only changed the sort direction on a header click, not the page's initial (no-click) order; now verified against the full rank hierarchy, not just the two originally-reported ranks.
- Fixed a false-positive registration rejection for חובה-track privates whose discharge date simply hadn't been recorded yet.
- Fixed duty locations not showing for non-admin users on the homepage's upcoming-duties list.
- Reworded an awkward Hebrew duty-count stat label, changed calendar hour labels to show "HH:00" instead of bare numbers, and replaced "פאז" with "שלב" in the algorithm help text.
- Fixed clicking a bug report row's status cell not always expanding the row; fixed a confusing UI state when a comment posts successfully but its attachment fails to upload (including a stale-state race when retrying the upload).
- Fixed login sometimes redirecting to a blank `/setup/telegram` page during a settings-load race; added a catch-all route as a safety net.
- Added missing Hebrew translations for 3 notification types and clarified the Telegram global setting's description.
- Fixed duplicate notifications when multiple swap candidates approve the same request.
- Bug report comments/attachments: added database indexes, per-report/per-comment count caps, and switched attachment uploads to a bounded read that rejects oversized files without buffering the whole file first.

### Chores
- Extracted a shared `PopoverDropdown` component (with keyboard Escape-to-close and ARIA attributes) and `CheckboxListDropdown`, removing duplicated dropdown logic from the shared data table component.
- Added test coverage for the duty-type breakdown chart and for the full rank-ordering hierarchy (not just the two ranks from the original bug report).

## 2026-07-30

### Features
- Personal constraint approval is now a two-step process — commander approval followed by duty-manager approval, both required by default and independently configurable in system settings — replacing the previous single-step approval.
- Commanders and duty managers can now mark a past duty as a no-show, which records an audit trail and automatically applies a score penalty.
- Hierarchy transfer requests are now capped at 5 per soldier per rolling 24 hours, and bug report submissions at 50 per reporter per rolling 24 hours, to stop abuse.
- Announcements now block a duplicate resend (same title, same sender) within 5 minutes of the original.
- Exemption requests now require a real, non-empty reason.

### Fixes
- Invite-code redemption is now atomic, closing a race condition that could let a single-use code be redeemed more than once by concurrent requests.
- Hierarchy transfer requests targeting a nonexistent destination node are now rejected instead of silently creating a broken request, and a soldier can no longer approve or reject their own transfer request even if they hold commander authority over the destination.
- Taking an open duty ("take free") now requires the original duty owner's consent and goes through the normal manager-approval gate, instead of instantly reassigning the duty.
- Fixed the personal-constraint approval change breaking legacy approvals-import workbooks and the frontend: a soldier's pending constraints no longer disappear from their requests list, and no longer show the wrong (rejected) status to approvers.

## 2026-07-30

### Features
- Excel export/import now covers system settings and bug reports as two new sheets in the existing unified pipeline. System settings round-trip as key/value pairs, validated against the same density and relax-ceiling rules the settings screen already enforces, with internal-only keys staying non-editable; bug reports round-trip with reporter, description, severity, route, status, and their JSON snapshot columns, and a mismatched reporter on an update row now surfaces as a warning rather than silently changing who's credited. Both sheets — in the export picker and the import review page — are admin-only.
- Added a "🏅 ניקוד" (scoring) tab to the help modal, showing every duty type's score-per-day live from the current configuration.

### Chores
- Fixed a test-infrastructure bug where a test file importing a route module during pytest collection could bake the wrong database host into the global DB engine before the test-container fixture had a chance to run, causing unrelated route tests to fail with a DNS resolution error; also updated a couple of tests whose expected error-message assertions had drifted from the app's current machine-readable error codes.

## 2026-07-29

### Features
- Soldier names throughout the swap cards (candidate list, approval status columns, marketplace requester line) are now clickable and open that soldier's profile, matching the pattern already used on the approvals screen.
- Two new system settings, soldiers.phone_public and soldiers.email_public (both default on), control whether a soldier's phone number and email are visible to anyone who can see their record at all, rather than only in-scope commanders/duty-managers. The soldier profile modal also gained a read-only email row — previously it showed phone but never email in view mode.

### Fixes
- Fixed stale default levels for the exemptions settings (who can grant a commander exemption, and who can view the underlying medical document) — fresh installs with no saved value now default to מרכז/מדור/ענף instead of the previous, incorrect defaults.

## 2026-07-28

### Features
- A soldier can now edit an already-open swap request afterward — adding more specific invitees or publishing it to the marketplace — via a new "Manage" button, instead of only being able to set this up when first creating the request.
- Swap approval status is now shown as separated per-side columns with bulleted approval lines and a color-coded (green/red/amber) summary per side, replacing the old single inline status line; the previously backend-only "require duty-manager approval" setting is now visible and editable in system settings.
- Admins can now import bug reports from JSON mirror files.
- Open swap requests are now automatically cancelled once their duty starts, with both the requester and any pending candidates notified — there's no one left to swap with once the duty is underway.
- System settings are reorganized into a clearer, soldier-facing-first grouping (16 groups → 15), with duty rest-hours moved out of גימלים and the upcoming-duty alert folded into the home-page settings group.
- The bug report form can now be submitted with Ctrl+Enter.

### Fixes
- On the swap approvals screen, the reject button (both whole-request and per-candidate) is now only shown to a commander/duty-manager who actually has authority over that side, matching how the approve button already worked — previously it appeared for anyone, and a commander with no relation to a specific candidate could reject that candidate's already-accepted swap by mistake.
- An invited candidate responding to a swap request no longer also sees the unrelated "I'll cover" marketplace button alongside their own approve/reject controls.
- The duty-manager approval line no longer claims "commander approval not required" when a soldier's branch simply has no duty manager scoped to it — it now shows an accurate, distinct message, consistently on both the soldier-facing and admin approval screens.
- The swap reason field is now labeled instead of rendered as unlabeled text.
- Approving a constraint could previously race ahead of a pending enrollment approval it should have waited for, and could send a duplicate enrollment notification — both fixed.
- The swap-request candidate list now shows a loading indicator instead of misleadingly claiming there are no eligible soldiers while the list is still loading.
- The bug report navigation trail now shows local time instead of raw UTC, and each entry is a clickable link to that page.
- On a swap request with 3+ participants, candidates beyond what fit the approval-status block could lose their name everywhere on screen (not just in that block) on narrow/mobile viewports; the block now scrolls horizontally instead of clipping, and the candidate list always shows names regardless.
- Fixed a global double-scrollbar bug: the document itself could scroll independently of the app's own internal scroll region, showing two competing scrollbars on the same page.
- Commander-exemption approval is now gated purely on commanding a sufficiently senior hierarchy node — a high rank alone (previously רס"ן and above) no longer bypasses that requirement.
- הקפצה פיקודית (forced callup) and Telegram notifications now correctly default to off everywhere (nav, routes, notification preferences) when unconfigured, matching their displayed default in system settings — previously only the settings page itself reflected "off" while every runtime check still treated the feature as enabled.
- A soldier's "pending enrollment approval" state no longer stays stuck for the rest of a session after an admin approves it — the app now polls until it clears, instead of only refreshing on login.
- The homepage's duty-type and score-comparison charts now read correctly for RTL (bars grow right-to-left, categories ordered so "me" reads first) instead of using the charting library's LTR default.
- Fixed a dark-mode-only bug where the swap approval card's per-side status color was either muddy (translucent tint stacking with the card's own background wash) or silently missing entirely on all but the first column, due to a Tailwind CSS specificity conflict with the column divider.

### Chores
- Seed data now includes one duty manager per branch, scoped to that branch, so the duty-manager approval step of the swap workflow can be exercised locally without manually creating one.
- Renamed the Hebrew term for the swap-covering side from מכסה to the more correct מחליף, consistently across the swap and reserve-coverage UI (leaving unrelated "quota" and "covers/encompasses" uses of מכסה untouched).
- Extended integration/unit test coverage for bug-report import and swap-approval workflows.

## 2026-07-27

### Features
- New Announcements feature: admins can broadcast org-wide, and commanders/duty-managers can narrow the target to specific units via a hierarchy checkbox tree, from a dedicated compose/history page. Announcements are read-tracked and shown with a distinct icon for system-wide vs. targeted broadcasts.
- Soldiers can now declare a military driving license (with expiry date) directly on the registration form, instead of only via a later profile-update request.
- Approving a soldier's enrollment now requires reviewing their full profile in a modal first — the quick-approve shortcut that bypassed it is gone. If the approver edits any field while reviewing, the soldier gets a notification listing exactly what changed.
- Swap requests are now unified: a soldier's request for a given duty is a single request that can combine specific invited soldiers and open-marketplace visibility at once, with every candidate able to compete for approval in parallel — the first to clear approval wins and the rest are automatically cancelled, replacing the old design where each invited/marketplace candidate created its own separate request.
- The help modal gained several new, permission-gated tabs (Hakpaza, Approvals, Import, and a live eligibility-checker), a live what-if recompute in the Fairness tab, a draft/publish section in the Algorithm tab, and a clickable, expandable version of the swap flow diagram.

### Fixes
- Modals across the app (bug report, help, and most other dialogs) no longer flash-closed immediately after opening — a React StrictMode timing issue in the shared back-button-close hook affected nearly every modal.
- Telegram notifications are now off by default until an admin explicitly enables them (previously defaulted to on).
- Password fields on login, register, change-password, and reset-password are now left-aligned instead of inheriting the app's RTL direction.
- "Rank in unit" on the home and my-duties pages now explains what position 1 means (highest normalised score, i.e. heaviest duty load — not "best").
- Phone numbers are now validated against Israeli mobile/landline formats on registration, profile updates, and enrollment-review edits (previously any string was accepted).
- `dev.ps1` now stops if migrations fail instead of silently starting services anyway, which previously surfaced as a confusing "role does not exist" backend connection error far from the real cause.
- Announcements: fixed duplicate notifications from the commander cascade, paginated the recipients endpoint, added error handling and role-gating to the compose page, fixed a stale unit name after removing a narrowed-scope chip, and disabled submit while scope is still loading for non-admins (which previously produced a confusing permission error).
- A duty dismissal's reason text is now redacted unless the viewer is an admin, an in-scope commander/duty-manager, or the affected soldier — previously visible to anyone who could see the calendar.
- Notification "mark as read" now actually records the read timestamp (previously always left null).
- Rejecting one specific candidate on a swap request no longer risks rejecting the entire request when the approver happens to be authorized on both the requester's and the candidate's side; admins and other broadly-authorized approvers can once again reject a swap even with no direct chain match; and two commanders approving different candidates on the same swap at nearly the same moment can no longer both finalize it.
- Hakpaza feature-flag gating, solver-explanation copy accuracy, a missing constraints tab, and duplicated algorithm-mode copy were corrected in the help modal.

### Chores
- Reconciled a duplicate/orphaned Alembic merge migration for the theme-preference and bug-reports heads, and another for the swap-requests and enrollment-fields heads — an expected hazard of concurrent feature worktrees in this repo.
- Extracted shared permission-check predicates (`authenticated`, `canApprove`, `canPlan`) into a new `auth/permissions` module.

## 2026-07-25

### Features
- Approvals data can now be exported to Excel and re-imported: 6 new sheets (exemptions, constraints, swap requests, enrollment requests, field updates, hierarchy transfers) with a dedicated export button and matching import-review tabs.
- Swap approval rosters and constraint/exemption/field-update/enrollment approval cards now show the nearest commander/duty-manager per row, computed live instead of from a stale snapshot, along with per-row rejection attribution.
- Exemption types can now be scoped to specific duty types/locations via a new eligibility matrix editor on the Duty Config page, enforced by the CP-SAT scheduling algorithm and required to be reviewed before creating a new exemption or duty type.
- Medical exemption documents can now be previewed in-app (PDF/image) with a download button; viewing them requires a configurable minimum command/duty-manager level, and the commander-exemption minimum command level is now configurable too.
- All date inputs across the app now use Israeli dd/mm/yyyy formatting and prevent picking a from-date after the to-date.
- Forced-callup routes/nav are now gated behind a `forced_callup.enabled` setting.
- The Potential page gained duty-type filter pills.
- Approve buttons across the Approvals page and soldier-profile modal now only appear for requests the current viewer can actually approve, computed server-side instead of guessed from a coarse role check.
- New global header search (Ctrl/Cmd+K or the header icon): fuzzy search across pages, soldiers, duties, units, quick actions, help topics, and in-page tabs (admin settings, approvals, swaps, transparency), fully RBAC-scoped server-side.
- New dark mode: a sun/moon/system toggle in the header, persisted per soldier and applied instantly on load with no flash.
- New in-app bug/feedback reporting: a floating trigger captures a screenshot and lets any soldier submit a bug report with a description and severity; admins get a dedicated review tab (list, detail, screenshot, status).
- The header logo now links back to the homepage; the header layout no longer overflows on mobile, and open modals/dialogs now close on the mobile/browser back button instead of navigating away.
- Personal constraint requests can no longer be submitted with a start date in the past — the date picker, submit button, and an inline error now all enforce it client-side, matching the existing server-side rule.

### Fixes
- Clicking an exemption-request attachment no longer fails — the download URL was hitting `/api/api/...` due to a duplicate prefix.
- The profile page's military-license expiry date field now has its own label.
- File uploads (exemption attachments, gimelim attachments, Excel imports) now validate real file content (not just the declared MIME type) both client- and server-side, enforce size limits, and sanitize stored filenames.
- Plain soldiers can now view another soldier's basic profile (read-only, privacy-redacted) instead of hitting a permission error.
- Backend error codes are now translated instead of leaking raw English strings into the Hebrew UI.
- Fixed a swap-override scope leak and an enrollment-approval confirm-dialog reliance issue.
- Eligibility exclusions now respect the caller's reference date instead of always using today's date.
- Approvals export/import: privacy redaction is now applied to export sheets, override-approval decisions surface correctly in the swap manager roster, and re-importing no longer wipes an existing decision-note reason when the redacted export sends a blank value.
- Unit calendar duty cells for full-day duty types now render/block correctly.
- Fixed a missing effect dependency in the shift-generation modal.
- Cumulative, score-per-day, and normalised scores are now rounded to 3 decimals.
- A duty manager whose account role isn't literally `duty_manager` (the common case — the `is_duty_manager` flag is what actually grants it) was incorrectly hidden from planning-page search results.
- Header search polish: fuzzy matching no longer floods results on short Latin-letter queries, the selection highlight is now visible in dark mode, Ctrl/Cmd+K now works under non-Latin keyboard layouts, and soldier/duty/unit results now show a subtitle (rank, date, or level).
- Bug-report screenshot capture no longer clamps to viewport height (the full page is captured), now has a timeout so a hang can't disable the trigger permanently, and its JSON mirror/payload size are hardened.
- Dark mode now applies via a CSS class instead of only following the OS media query at load, and now updates live if the OS theme preference changes while the app is open.

### Chores
- Removed a dead edit-mode exemption-map prefetch in the duty-type form modal.
- Stubbed `matchMedia` in the App test environment (needed once dark-mode detection was added) to fix a test that had started failing.

## 2026-07-23

### Features
- The hierarchy tree now shows its full extent to every viewer (not just a commander's own scope), with per-node edit gating, auto-expand, and the viewer's own node highlighted; commanders' `HIERARCHY_MANAGE` permission is now scoped rather than all-or-nothing.
- Soldiers can now see their remaining personal-constraint ("ימי אילוץ") days for the current reset period directly, alongside the existing submission-cap enforcement.

### Fixes
- The Telegram account-linking panel on the profile page no longer renders when Telegram is globally disabled.
- The push/Telegram notification preference column is hidden when Telegram is globally disabled.
- Restored missing translations for two notification preference types.
- Fixed the military driving-license expiry field label.
- The score-adjustment history table now uses Hebrew date formatting.
- The calendar's week/3-day views no longer force horizontal scroll at desktop widths.
- Duty cells no longer render with an invalid empty color.

### Chores
- Capped the vitest thread pool and fixed stale/flaky frontend tests.

## 2026-07-22

### Features
- Import review: row-detail modal exposing full field data across all import tabs (hierarchy, soldiers, duty_locations, duty_shifts, assignments), plus inline editing and field-override support (with duty_type remap on assignments) so rows can be corrected directly in the review table instead of re-uploading a fixed sheet.
- Shift swap approval now requires one commander AND one duty-manager sign-off per side (configurable, on by default), with a same-approver shortcut when one person covers both sides; the swaps help screen and a new page-level help icon explain the new flow.
- The transparency page can now be restricted to commanders of specific hierarchy levels (e.g. section/branch/team) plus duty managers and admins, via a new admin setting; open to everyone by default.
- Soldiers can see how many personal-constraint ("ימי אילוץ") days they have left in the current period, which resets quarterly, semi-annually, or annually per a new admin setting (default quarterly) — and the submission cap now enforces the same period-scoped count the display shows.
- Releasing/discharging a soldier now asks for a start date first, via a small modal, instead of a plain confirmation dialog.
- Requesting a swap from a specific soldier now shows a table of eligible, available soldiers sorted by hierarchical distance, with a configurable cap (default 5) on how many can be selected at once.
- The soldier profile modal now shows service type (חובה/קבע) and driving-license status/expiry, with the license fields editable.
- Reordered the unit calendar's view buttons to 3-day, week, month (month remains the default view).

### Fixes
- Per-IP and per-account login rate limiting no longer collapses every client to the same bucket: the Vite dev proxy and production uvicorn now trust the reverse proxy's `X-Forwarded-For`/`X-Forwarded-Proto` headers instead of seeing every request as coming from the proxy itself.
- The login page's rate-limited "try again in N seconds" message now shows a real countdown instead of an unfilled `{{seconds}}` placeholder (slowapi's `Retry-After` header wasn't being sent).
- Swap-request errors no longer leak the raw `cover_not_eligible:` error code — only the underlying reason is shown.
- Fixed a gap where accepting one of several parallel swap offers for the same duty could leave another offer's approval still pending instead of being cancelled.
- Submitting a targeted swap request with no soldier selected no longer silently falls back to posting an open request to the whole board.
- The release-from-duty modal's date-range picker now prompts for the start date before the end date, matching the actual click order (it previously asked for the end date first).

### Chores
- Split `.env` into a committed `.env.defaults` (non-secret dev config, so a fresh clone works out of the box) and a gitignored `.env` for the Telegram bot token and machine-specific overrides.

## 2026-07-21

### Features
- Affected soldiers are now notified across more workflows: enrollment-request approval/rejection, hakpaza call-up approval (both pulled and replacement soldiers), duty-day override substitutions, and reserve call-up/dismissal (primary and reserve).
- Job creators are now notified on all algorithm-run terminal states, not just success/exception.
- `is_career` (קבע) is now derived automatically from rank and service dates instead of being set manually; חובה-only ranks can no longer be combined with קבע status, and registration always starts as חובה.
- New system setting restricting swaps to soldiers sharing a common hierarchy ancestor at a configurable level, enforced on both directed and open-board swap requests.
- New `telegram.enabled` kill-switch: disables Telegram notification delivery and hides all Telegram UI when off.
- Moving a soldier between hierarchy units now creates a transfer request requiring the destination commander's/duty manager's approval instead of an immediate move, with a new "transfers" tab on the Approvals page.
- System settings can now be exported/imported as JSON from the admin settings page.
- Configurable email-domain hint shown as a placeholder on the registration and profile email fields.
- Login page now shows the failed-attempt count against the lockout threshold; the attempt that reaches the threshold now locks the account immediately (429) instead of on the following attempt.

### Fixes
- Self-approval of a soldier's own constraint/exemption requests is now blocked; commander-exemption grants must go through the dedicated endpoint (not the generic one), with notifications on direct grants, and duty managers are notified when a commander approves their exemption-request step.
- `dismiss_and_reallocate` now authorizes the covering reserve's own scope, not just the primary soldier's.
- Shift-template endpoints now use `SHIFT_MANAGE` instead of `ASSIGNMENT_MANAGE`, restoring duty-manager access.
- Swap notifications now cover no-approval paths for both parties and the covering soldier on reject/cancel.
- Single/bulk shift-assignment removal is now audit-logged and notifies affected soldiers, with per-item exceptions isolated so one failure doesn't block the rest of a bulk operation.
- Excel import apply now enforces duty-manager scope and adds audit-logging/notifications, with per-row notification failures made non-fatal to the response.
- `announce()` no longer reuses the `ALGORITHM_RUN` action, and non-admin broadcasts now enforce scope.
- Missing exemption-status translations and untranslated `cover_blocked:*` swap errors now show proper Hebrew messages.
- Duty type name is now embedded directly in the effective-duty/swap APIs, fixing a generic "תורנות" label showing on the dashboard and swap pages when a lookup failed.
- Exemption-request attachment files now download with the auth token, fixing a "missing token" error when viewing them from the Approvals page.
- Commander-dashboard pending-swap count used the wrong status literal; soft-deleting a soldier now cancels their pending exemption/constraint/swap requests instead of leaving phantom approvals behind.
- Requesting a swap now uses soldier search instead of a raw personal-number field, fixing a crash on invalid input; added an app-level error boundary as a general safety net.
- Soldier is now notified when their enrollment request is rejected.

## 2026-07-20

### Features
- **Swap chain-of-command approval** — swap requests now route through each side's full commander chain (nearest-first), with per-commander approval endpoints, a `swap_manager_approvals` table (backfilled for in-flight swaps), and chain-of-command status surfaced on both the Swaps page and the manager Approvals page; soldiers can self-approve their own side.
- **Enrollment gate** — soldiers with a pending enrollment request are blocked from creating swaps/constraints/exemption-requests via a new `require_enrolled` dependency, see a pending-enrollment banner with forms disabled, and get notified when their enrollment is approved or rejected; `enrollment_pending` is now exposed on `/me`.
- **Import review inline editing** — new `ImportRowFieldsModal` lets duty_types/exemption_types import rows have their eligible units, requirements, and applies-to lists edited directly in the review table, which now also shows full field detail for both sheet types.
- **Shift-templates import/export** — a new `shift_templates` sheet is parsed, resolved against duty types/locations/eligible units, and creates/updates `ShiftTemplate` rows on import-session confirm; the export page now offers select-all and splits system data into 4 separate sheets, reconciled with the full-data round trip.
- **Per-account login rate limit**, alongside the existing per-IP limit.
- Soldier profile date fields now get cross-field validation (e.g. discharge after enlistment); self-submitted exemption/constraint requests are capped at 364 days.
- Exemption/constraint date ranges now show their span duration alongside the dates.

### Fixes
- Swap manager approval now requires only a single chain commander to sign off, not all of them; commander chain order comes from an explicit `chain_order` column instead of relying on `created_at`.
- `COOKIE_SECURE` now defaults to `false` in the env template, with a warning on http/secure-cookie mismatch (was breaking non-HTTPS deployments).
- Exemption type name now shows on the exemption-request approval row; any authenticated soldier can list duty types (was over-restricted).
- Fixed several react-query migration regressions: `TelegramSetupPage` polling and `SystemSettingsPage` cache invalidation, a `SwapsPage` hierarchy query-key collision with other `fetchFullTree` consumers, missing `lang=he` on date inputs in `PotentialPage`/`CommanderExemptionGrantForm`, and a test render missing its `QueryClientProvider` wrapper.

### Chores
- Migrated nearly every page's data fetching from manual `useEffect`/state to react-query, backed by a new central query-key registry (`frontend/src/queryKeys.ts`).
- Batch-loaded swap manager approvals in the pending() bulk listing to avoid N+1 queries.
- Disabled fsync on the test Postgres container to speed up the test suite.

## 2026-07-08

### Features
- **Config export/import UI polish** — unified the export page into a single checkbox panel producing one merged workbook; added duty_types/exemption_types and duty_locations/hierarchy review tabs to the import session UI, backed by typed row interfaces for the 4 new sheets, with an end-to-end round-trip test.

### Fixes
- `create_duty_type`/`update_duty_type` now receive `start_time`/`end_time` from callers.

### Chores
- Fixed stale test expectations left over from the config-export-import + import-export-assignments merge, and switched hardcoded 2026 dates in duty-block/algorithm-bridge tests to relative dates so they don't become time-bomb failures.

## 2026-07-07

### Features
- **Config export/import (core)** — new `GET /config/export` endpoint and import-sheet parsing/resolution for duty_locations, hierarchy, duty_types, and exemption_types, with dm-scope diffing and forward-parent linking on commit, blanking `requirements_json` instead of writing the literal string `"null"` on export, and an updated import-session row summary.
- **Exemption-type disable/delete** — deleting an in-use exemption type now offers a reason-gated disable (bulk-revoking its active exemptions) instead of failing outright, with a new `active` flag, re-enable support, and delete/disable UI; revoking an exemption now requires a reason via a new `ReasonPromptModal` (skipped for already-expired exemptions).
- Transparency page's unit filter is now searchable.

### Fixes
- `duty_types` import parsing preserves `reserve_minimum=0` and reads the correct `eligible_units` column; hierarchy and duty_types added to the parser's known sheets.
- Hierarchy import rows route commander assignment through `set_commander` on create, not just update; hierarchy-node name mappings now reach the resolver.
- `active=False` now applies on duty_location/duty_type create, not just update.
- Explicit `response_model=None` added to the 204 DELETE endpoint.
- Military-license date label clarified and its value formatted in approvals.
- Duty-history revoke fields (reason/revoker) now gated behind `can_see_private`.

## 2026-07-06

### Features
- **Duty-assignment import/export** — a new `assignments` sheet resolves rows to soldiers/shifts and creates `DutyAssignment` records on import-session confirm, with its own review tab, an assignments count in the session summary, and a `GET /import/export` full DB-state round-trip endpoint.
- **Exemption revocation reason** — revoking an exemption now requires and records a reason, sends duty-manager/soldier notifications, and no longer hard-deletes not-yet-started exemptions; duty-history entries now show the revocation reason and who revoked it.
- **Registration** now requires phone, email, gender, rank, and service dates; soldiers can request mandatory-end/discharge date changes from their profile.

### Fixes
- Revoked exemptions are excluded from potential/scoring eligibility checks.
- Approval/rejection actions surface the backend's real error detail on failure.
- Partially-filled exemption/constraint import rows are rejected with a clear message instead of crashing.
- Assignment creation wrapped in a savepoint for parity with duty-shift creation.
- Shared-IP login rate limit raised, with retry-after time shown.
- Import now falls back to full-name match when `personal_number` is unrecognized.

## 2026-07-04

### Features
- **Military driving license (רשנ"צ)** — new license types, a "requires license" eligibility rule, rank-gated `MILITARY_LICENSE_DECIDE` approval action, and a request UI on the soldier profile page.
- **"כלל המסגרת" whole-org rows** — a stable aggregate row/label added to the potential table, the transparency sub-hierarchy tab, and above hierarchy tree roots, so org-wide totals stay visible regardless of scroll position.
- **Partial-exemptions column** — potential calc and the `/potential` route now flag and expose soldiers with partial duty-type exemptions; surfaced as a new column in the potential table.
- **`ExemptionTypeViewModal`** — permission-gated view/edit modal, wired to the exemption chips already shown elsewhere in the UI.
- **Algorithm page**: run start/finish timestamps shown; mark-all-read label fixed.
- **Hour-aware calendar week view**; effective-duty `end_date` is now treated as exclusive.
- **Duty-type/duty-shift dialogs** now pre-fill from unresolved import names.

### Fixes
- **Bootstrapped root/holding node** no longer gets orphaned beside the root during reseeding — it's now correctly nested under it.
- **Exemption-type edit modal** now surfaces an error message when a save fails.
- **Duty-type selection** re-syncs correctly when reopening the edit modal; added missing edit/cancel i18n keys.

### Chores
- **Refactor**: extracted `can_see_private_node` helper to centralize scope-based private-field checks.
- Added a health-check path to the frontend dev launch config.

## 2026-07-03

### Features
- **Potential-based duty responsibility** — new `/planning/potential` page with a drill-down table, hierarchy indentation, column tooltips, % of parent, סד"כ column, eligible-percentage, soldier rank/clickable names, exemption details, and Excel export. Backed by a new `compute_potential` engine, `PotentialModifier` model with CRUD + audit trail, and `POTENTIAL_READ` / `POTENTIAL_MODIFIER_MANAGE` actions gated to duty managers and רסן+ commanders. Own-subunit potential now also shown on the command dashboard.
- **Sequential dual-approval exemptions** — exemption requests now flow through commander approval then duty-manager approval (`pending_commander` status), with two-stage status/actions surfaced in the UI.
- **פטור פיקודי (commander exemption)** — single-step grant endpoint and soldier-view grant form, gated by rank/מדור+/DM; the regular request flow now blocks commander-exemption types.
- **Shift quotas auto-split by potential** — new `compute_potential_split` service, `GET /shifts/quota-split-preview`, a `shifts.auto_split_node_quotas` system setting, and a "split by potential" button in the shift quota editor; quota rows now show their lowest-common-ancestor label. Added a rerun-algorithm button to `ShiftFormModal` for existing shifts.

### Fixes
- **Potential eligibility** now respects the `allowed_service_types` filter, matching `eligibility.py`.
- **`PATCH /exemption-requests/{id}`** repaired after the status rename; blocks retargeting to commander-exemption types.
- **Registration flow**: validates exemption type and date range; fixes a stale pending status.
- **`grant_commander_exemption`** now validates its date range.
- **Discharged-soldier reason key** now translates correctly in the Hebrew UI.
- **Potential table** rows now ordered by real hierarchy instead of raw API order.
- **Dashboard**: per-node potential fetches use `Promise.allSettled` for resilience; table headers i18n'd.

### Chores
- **Refactor**: extracted `dm_scope_covers_target` helper (drops a full-table scan); scoped potential queries to subtree and hoisted imports to module level.
- Added `logs/` to `.gitignore`.

### Docs
- Design specs and implementation plans for potential core, exemption flows, shift potential-split quotas, and potential page improvements; documented פוטנציאל and פטור פיקודי concepts in the help modal.

## 2026-07-02

### Features
- **Transparency exemptions column** — a `פטורים` column on the transparency soldiers tab plus exemption-count aggregates on the sub-units tab, scope-gated via a new `can_see_exemption_aggregates` flag and `TransparencyOut` type on `/scoring/transparency`.
- **Import review UX** — unmatched import names now resolve through an inline fuzzy-picker combobox (later replaced by a two-section `Combobox`), with name mappings applied on reparse; per-row error messages shown next to the שגיאה status chip; row-selection label renamed to אישור/דלג.

### Fixes
- **Import resolvers**: guarded against malformed `mapped_id` values when parsing UUIDs; lookup fetch errors now surface in the import review page; combobox query stays in sync on prop changes.
- **`ImportSessionReviewPage` tests** repaired after the combobox picker rewrite.

### Chores
- Removed dead `shift_templates` import support; added prior planning docs.

### Docs
- Design spec and implementation plan for import fuzzy name mapping and the transparency exemptions column.

## 2026-07-01

### Features
- **Excel import sessions** — replaced the old one-shot import with a session-based flow: upload creates a session, a review page resolves unmatched soldiers/duty-types/hierarchy nodes inline (with prefill from unresolved names), and confirm/cancel/done support partial acceptance with per-row savepoints so failed rows have zero persisted effect. Backed by a pluggable import-parser registry (`v1_standard` parser targeting `duty_shifts`), a new `import_sessions` table, and a DM-scope check helper shared across import rows. Upload now enforces a `.xlsx` extension check on both ends.
- **Sub-unit shift quotas** — `duty_shift_node_quotas` table, a quota service with validation, `PUT /shifts/{id}/quotas`, quota allocation UI in `ShiftFormModal`, exact per-node quota enforcement in the CP-SAT model (respecting soft-coverage mode), and one-level-up quota relaxation (manual + auto modes) wired into the solver bridge.

### Fixes
- **Import session routes**: ownership enforced on all mutating endpoints, not just GET detail; error handling, cancel confirmation, and a double-click guard added to the session list page; backend error detail now surfaces on upload failure.
- **Migration**: merged alembic heads for dual-approval enrollment and import-sessions/shift-quotas landing together.
- **`UnifiedSoldierModal`**: restored `is_officer`-based ALAL field gating.
- **`CHANGELOG.md`** import path corrected after it moved into `frontend/`.

### Chores
- Removed the dead `importExcel` API client, superseded by import sessions.

### Docs
- Documented Excel import sessions and sub-unit shift quotas in the README.

## 2026-06-30

### Features
- **Dual-approval enrollment flow** — enrollment now requires both a commander approval and an exemption-status check before a soldier is activated as career. `EnrollmentApprovalModal` lets commanders review pending enrollment requests from `ApprovalsPage`; approving/rejecting an exemption request tied to an enrollment now automatically re-checks and triggers `try_activate`. Registration sends `is_career` and links exemption requests to the enrollment request, notifying commanders and duty managers.
- **`PATCH /exemption-requests/{id}`** and a DM-level filter for enrollment-linked exemptions; enrollment pending list enriched with soldier data; **`PATCH /enrollment-requests/{id}`** added.
- **Public `GET /auth/exemption-types`** endpoint so the registration page can populate the exemption-type combobox before login.
- **Soldier lookup endpoint** — name / personal-number / hierarchy filters, used by the new import-lookup support endpoints for duty types and hierarchy nodes.

### Fixes
- **ALAL alert** now shown only for officers and career soldiers.
- **Hierarchy edit button label** clarified to make edit intent unambiguous.
- **Dismiss-from-duty buttons** hidden for non-managers.
- **Soldier lookup** now queries all roles (was missing some); N+1 fixed by bulk-loading hierarchy node data instead of per-row lookups; unused imports removed.
- **Rate limiter** added to the public exemption-types endpoint.
- **Migration downgrade** now uses the hardcoded FK constraint name instead of a lookup that could resolve incorrectly.
- **Enrollment PATCH**: re-authorizes when `requested_node_id` changes; commits instead of only flushing; fixed `end_date` null-clear; calls `try_activate` for enrollment-linked exemptions; raises `EnrollmentError` instead of asserting in `try_activate`.
- **Quick-approve buttons** no longer bubble their click event; removed an unused `useTranslation` import from a modal; renamed a shadowing map parameter (`t` → `et`) that collided with `useTranslation`'s `t`.
- **Registration exemption combobox** now correctly sends `is_career`.
- **`min_dm_level_rank` setting**: guarded its `int()` cast against `ValueError`.

### Docs
- Added an Excel import parser guide covering the import-lookup endpoints' format, plus date-format notes and a complete example JSON.

## 2026-06-30

### Features
- **`PasswordStrengthHint` component** — live password-policy feedback; registration, reset-password, and change-password forms now gate their submit button on the hint reporting a valid password.
- **Production hardening** — DB connection pooling, liveness/readiness probes, a dedicated threadpool for the solver, JSON structured logging, and HSTS enabled by default.

### Fixes
- **Broken test passwords** after the password-policy tightening; a malformed `Content-Length` crash; general asyncio modernisation.
- **`CHECK` constraints** added to prevent `start_date > end_date` across duty, constraint, and exemption tables.

### Chores
- **Perf**: fixed N+1 queries in the soldiers list, hierarchy nodes, and node registration paths.

## 2026-06-29

### Fixes
- **Deployment artifact corrections** — WAL health check, HSTS header, container discovery, and a restore guard.

## 2026-06-28

### Features
- **Per-user algorithm job seen state** — clicking a done or failed algorithm run marks it as seen, immediately removing it from the תכנון nav button badge and the per-section chips in `ShiftsManagementPage`. Seen state is persisted per user in the database (`algorithm_job_seen` table) so it survives page reloads and is consistent across devices.
- **"Mark all as seen" button** — added to both `AlgorithmPage` and `ShiftsManagementPage` to clear all unseen done/failed runs at once.
- **`AlgorithmSeenContext`** — React context wrapping the app with `seenIds`, `seedSeenIds`, `markJobSeen`, and `markAllSeen`. Badge counts re-render immediately on interaction without waiting for the 30-second poll.

### Chores
- **Removed `seenAlgorithmJobs.ts`** — deleted the old `localStorage`-based seen tracking utility; context is now the sole source of truth.

---

## 2026-06-27

### Features
- **Shifts table "תת יחידה אחראית" column** — new column after "מיקום" shows which sub-unit(s) are eligible for each shift ("כולם" when unrestricted). Supports a collapsible hierarchy tree filter in the column header.
- **`HierarchyNodeFilter` component** — reusable collapsible tree picker for filtering by hierarchy nodes, used in the shifts table column filter.
- **`customColumnFilter` on `DataTable`** — new `ColDef` field for fully-controlled column filter dropdowns: provide a React node for the popup content and a predicate function for row filtering, replacing the built-in exact-match checkbox list.
- **Collapsible `SubHierarchySelector`** — each node now has a ▾/▸ expand/collapse toggle; the tree starts fully expanded. Used in the shift, shift template, and duty type forms.

### Fixes
- **`ShiftFormModal` scroll on mobile** — modal container now has `max-h-[90vh] overflow-y-auto` so tall forms are scrollable on small screens.
- **`DismissalModal` date range picker** — replaced broken "snap to nearest endpoint" heuristic with a two-phase model (click FROM then click TO). The old logic made it geometrically impossible to select a range ending near the start of a long shift. Phase starts at "to" so the first click on a pre-filled full-range naturally narrows the end date.

### Features
- **Post-solve swap pass** — after CP-SAT solving, a greedy swap pass transfers individual duties between over- and under-loaded soldiers to reduce effort imbalance without re-solving. Runs on every decomposition mode (interleaved, effort-rounds, calendar, monolithic).
- **Duty-count progress reporting** — progress bar now advances proportionally to duties solved rather than batches completed, giving smoother and more accurate progress indication. A distinct "מאזן עומסים…" label appears during the swap pass (at 94 %).

### Chores
- **Effort formula: cumulative weighted ratio** — changed effort formula to use cumulative weighted ratio for better convergence.
- **`useDutyManagerPortfolio` hook** — shared hook extracted from `HierarchyTree` and `TeamHierarchyPage` (worktree merged; master uses `usePortfolioDialog` naming).
- **SIGABRT debug handler removed** — removed temporary SIGABRT signal handler from algorithm job runner.
- **`dev.ps1` process cleanup** — more reliable stale process killing on dev server startup.

---

## 2026-06-26

### Features
- **Transparency export respects all active filters** — "ייצוא לאקסל" button moved directly above each table (soldiers and sub-units) and now exports only the currently visible/filtered/sorted rows instead of the full unfiltered dataset. Button is disabled when zero rows are visible.
- **Client-side Excel export** — new `ExcelExportButton` component generates `.xlsx` files in the browser using SheetJS, replacing the old backend-driven download endpoints.
- **Planning > Export page migrated to client-side** — `ExportPage` now computes the full unfiltered export locally (DFS-ordered by unit for soldiers, shallowest-first for sub-units) without calling the backend.
- **Hierarchy scope picker on duty forms** — duty types, shift templates, and shifts now have an eligible-units picker (hierarchy scope) so a duty can be restricted to a specific sub-tree of the hierarchy.
- **Algorithm partial results on cancel** — salvages partial solver results when a batch job is cancelled and retries interrupted jobs automatically.

### Fixes
- **DataTable infinite re-render loop** — `onVisibleRowsChange` callback previously created a new array on every render, causing `useEffect` to fire every render and loop indefinitely. Fixed by memoizing visible rows on actual filter/sort state and reading column defs via a ref.
- **Fairness: thin-quarter denominator** — inflate the denominator by pending workload before computing each soldier's effort share, preventing score inflation for soldiers with very few active days in the quarter.
- **Fairness: run workload in effort-share denominator** — the algorithm's own duty workload is now fed into the effort-share denominator so the solver accounts for the current run's load when computing fairness.
- **Sub-tree eligibility in candidate listing** — candidate filtering is now sub-tree-aware and correctly excludes unassigned soldiers.
- **ExportPage `dfsOrder`** — fixed parent-child hierarchy construction to build from `parent_id` map instead of relying on the unpopulated `children` field returned by the flat API.

### Removed
- Backend transparency export endpoints (`GET /transparency/export`, `GET /transparency/sub-units/export`) and their `openpyxl`-based helpers — superseded by client-side export.
- Frontend `downloadTransparencyExport` / `downloadSubUnitsExport` API functions.

---

## 2026-06-25

### Features
- **RBAC capability model** — replaced role-string checks throughout the frontend with real `is_commander` / `is_duty_manager` capability flags exposed on the `/auth/me` response. Gates nav tabs, approval widgets, duty-config management, algorithm page, explanation redaction, hakpaza flow, and private-field visibility on actual DB-backed capabilities instead of the display-only role label.
- **Role label derived from real capabilities** — `Soldier.role` is now computed from the soldier's actual node assignments and DM scope rather than a stored string; displaced commanders are handled correctly.
- **Lexicographic range tie-break** — algorithm solver uses a lexicographic range tie-break for cross-batch fairness.
- **Backend & bot crash logging** — backend and Telegram bot now persist startup/shutdown/crash markers to rotating log files outside the container; `dev.ps1` supervisor auto-restarts on crash.
- **Crash-detecting supervisor in dev.ps1** — detects backend/bot crashes and automatically restarts the affected process.

### Fixes
- **DM scope derived from real data** — duty-manager scope is computed from actual DB assignments regardless of the role display label.
- **bot restart loop** — `run_dev_bot.py` no longer restarts on a clean (deliberate) bot exit.
- **`run_dev_bot.py` kills stale supervisors** — cleans up `run_dev_bot.py` parent processes in addition to bot children.
- **Explanation redaction gated on real DM capability** — previously gated on role string.
- **Hakpaza initiate/approve gated on real capability flags**.

### Removed
- Unused role-override endpoint (`PATCH /soldiers/{id}/role`) — role is now derived, never set directly.

---

## 2026-06-24

### Features
- **Gimelim merged into DismissalModal** — gimelim (reserve call-up) flow is now a mode toggle inside the unified DismissalModal rather than a standalone dialog.
- **Hierarchy level types** — hierarchy node levels are now managed from the database (`hierarchy_level_types` table) instead of being hardcoded. Admin/duty-managers can create, rename, reorder, and delete level types. The hierarchy tree, level dropdowns, and node-edit dialog all drive from the DB-backed types.
- **EditNodeDialog** — replaces the old RenameNodeDialog; includes a level dropdown driven by DB level types and an inline level-type manager.
- **Algorithm batch results UI improvements** — run status, assigned/total coverage display, and assignment page cleanup.

### Fixes
- **Level type management widened to duty_managers**.
- **AddRootNodeDialog** — guarded against rendering before level types load.
- **`change_node_level` children-rank boundary** — test coverage added and edge case fixed.

---

## 2026-06-23

### Features
- **Algorithm run badges** — colored status badges (pending / running / done / failed) on the algorithm runs section header and on the Planning nav tab/sheet item. Cancelled jobs are excluded from badge counts.
- **Private fields access control** — soldier private fields, constraint reasons, and exemption types are redacted from admins and unauthorized viewers; DMs see only soldiers in their scope. Frontend shows "מידע פרטי" placeholder for redacted values.
- **Algorithm job FK and score columns** — `duty_assignments` table gains `algorithm_job_id` and `score` columns; a fast-path query uses the FK to load proposals for a given job.
- **Approvals page embed** — pending swap, field-update, and exemption responses embed soldier/node names and files server-side, eliminating N+1 fetches.
- **Unit calendar "כלל המסגרת" option** — added full-corps view option to the unit calendar filter.
- **Cover ineligibility tooltip** — shift cover button shows the ineligibility reason as a disabled-button tooltip.
- **Assigned/total coverage in algorithm job list**.
- **Success message after clear all assignments**.
- **`can_see_private` capability** added to authz, gating all private-field access.

### Fixes
- **Clear all assignments** — bulk UPDATE instead of per-row ORM loop; shifts table refreshes after operation.
- **Exclusive end-date display** — end dates now display and fire overlap detection correctly.
- **15 miscellaneous bug fixes** — shift tests, nav badge computation, algorithm run section improvements.

### Performance
- **Batch-load** soldiers/nodes in pending field-updates, swap, and exemption handlers.
- **Parallel ApprovalsPage** initial load.
- **Embed exemption files** in pending exemption response.

---

## 2026-06-22

### Features
- **Project renamed to Justice** — package names, database name, API title, ICS UID domain, docs, and CLAUDE.md all updated from "callofduty2 / Call of Duty 2" to "justice / Justice".
- **Saturation-aware relaxation restart** — solver detects saturation clusters (groups of duties that compete for the same small candidate pool) and explains them in the Issues tab; suppresses misleading "add soldiers" recommendation when the real constraint is a scheduling conflict.
- **Retroactive gimelim release** — `preview_gimelim` and `commit_gimelim` now accept a backdated `from_date` so a soldier can be released from a duty that already started.
- **Batch time limit raised** — default `batch_time_limit_seconds` increased from 60 to 120.

### Fixes
- **Relaxation restart** — restarts the whole component from scratch on relaxation instead of patching residual state.
- **Gimelim audit log** — records the actual gimelim call-up `from_date`, not the shift start date.
- **Exclusive end-date misfiring** — single-day duties using exclusive end dates no longer misfire as overlapping.
- **Migration revision collision** — resolved a migration revision collision between the shift-templates branch and the main branch.

---

## 2026-06-21

### Features
- **Duty day calculation fix** — effort score now uses `score_days` (actual duty-day windows) instead of calendar days touched, preventing inflation for multi-day duties that span non-duty days.
- **Shift start/end times** — `duty_shifts` and `duty_assignments` gain `start_time` / `end_time` columns; times are copied from the shift template onto generated shifts and from the source shift onto gimelim-promoted assignments.
- **Solver block score uses score_days** — the CP-SAT solver's per-block effort score uses `score_days` for consistency with the transparency score.
- **`--fair` seed flag** — `generate_seeds` CLI accepts `--fair` to skip exemptions and constraints for a clean fairness baseline.

### Fixes
- **Count-spread tiebreaker weight raised** — fixes a duty-concentration bug where multiple duties were assigned to the same soldier when spreading was possible.
- **Day-weight division by zero** — guarded against zero-day assignments in the per-day effort weight calculation.
- **Exclusive end-date in tests** — corrected single-day duty fixtures to use exclusive end dates consistently.
- **HH:MM format validation** — manually-created shift times are validated for correct format.

---

## 2026-06-20

### Features
- **Shared searchable Combobox** — new `Combobox` component with keyboard navigation and ARIA roles, wired into: hierarchy node, rank, exemption type, duty type, location, candidate, reserve assignment, and batch-filter dropdowns across all major forms.
- **Shift template auto-roll until-date** — shift templates gain an `auto_roll_until` date field; the roll-horizon generator clamps generation to this date. A live instance count picker is shown when configuring it.
- **Solver input snapshot** — `algorithm_jobs` stores a snapshot of solver inputs at run time so `export-inputs` can replay a completed job's exact inputs.

### Fixes
- **Export-inputs replay** — fixed so it uses the snapshotted inputs from the completed job rather than recomputing.
- **Required-field guard** — restored a required-field guard lost when the select's `required` attribute was dropped.
- **Soldier profile edit form** — removed erroneous `sm:grid-cols-2` making the form two-column on small screens.

---

## 2026-06-19

### Docs
- Design spec and implementation plan for shared searchable Combobox component.
- Design spec and implementation plan for shift template auto-roll until-date.
