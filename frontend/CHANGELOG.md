# Changelog

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
